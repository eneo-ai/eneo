# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Column-only reads and row-level member writes for tenant-admin oversight.

Rules every statement here keeps:
- it is scoped to ``Spaces.tenant_id`` or to a space id that was checked
  against the tenant, so a foreign id never matches;
- it selects explicit columns, never the Spaces or Assistants entities (their
  ``selectin`` relationships would load more than oversight may see);
- it never selects a credential column (website auth, MCP env vars, tokens)
  and never reads document, question or file content.

The space aggregate loader (``SpaceRepository.one`` and friends) is never used:
it skips the tenant filter, hydrates attachment content and decrypts website
credentials. Statements run one after another; asyncpg allows one query at a
time per session.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from eneo.database.database import AsyncSession
from eneo.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from eneo.database.tables.app_table import AppRuns, Apps, AppsPrompts
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    AssistantMCPServers,
    Assistants,
    AssistantsFiles,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.capabilities_table import (
    AssistantCapabilities,
    SpaceCapabilities,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version
from eneo.database.tables.integration_table import (
    Integration,
    IntegrationKnowledge,
    TenantIntegration,
    UserIntegration,
)
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesEmbeddingModels,
    SpacesTranscriptionModels,
    SpacesUserGroups,
    SpacesUsers,
)
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.database.tables.websites_table import Websites
from eneo.database.tables.widget_usage_table import WidgetDailyUsage
from eneo.database.tables.widgets_table import Widgets
from eneo.main.exceptions import NotFoundException
from eneo.sessions.helper_filters import exclude_helper_run_sessions
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import (
    APP_RUN_ACTIVITY_WINDOW_DAYS,
    MANAGEABLE_USER_STATES,
    USAGE_WINDOW_DAYS,
    DirectMembership,
    GroupMembership,
    MembershipSnapshot,
    higher_role,
)
from eneo.spaces.oversight.oversight_models import (
    AdminPrincipal,
    AdminSpaceApp,
    AdminSpaceAssistant,
    AdminSpaceGroupChat,
    AdminSpaceKnowledgeSource,
    AdminSpaceWidgetRef,
    Capability,
    IntegrationType,
    OversightClassification,
    OversightKnowledgeRef,
    OversightModelRef,
    OversightPersonRef,
    OversightRef,
    UpdateInterval,
)
from eneo.spaces.space_repo import (
    COLLECTION_SOURCE,
    INTEGRATION_KNOWLEDGE_SOURCE,
    WEBSITE_SOURCE,
)
from eneo.spaces.utils.space_utils import effective_space_ids_for
from eneo.users.user_repo import tenant_admin_user_ids_select
from eneo.widgets.domain.widget import WidgetStatus

SpaceKind = Literal["shared", "organization", "personal"]

_UGU = usergroups_users_table
_MANAGEABLE_STATES = sorted(MANAGEABLE_USER_STATES)
_UPDATE_INTERVALS: frozenset[str] = frozenset(
    {"never", "daily", "every_other_day", "weekly"}
)
_CAPABILITIES: frozenset[str] = frozenset({"web_search", "image_generation"})
_INTEGRATION_TYPES: frozenset[str] = frozenset({"sharepoint", "confluence"})
# Website.is_auto_disabled: crawling was switched off after this many failures.
_AUTO_DISABLE_FAILURES = 10


def _live_group() -> sa.ColumnElement[bool]:
    return sa.or_(UserGroups.state.is_(None), UserGroups.state != "deleted")


def _shared_space_ids(tenant_id: UUID) -> sa.Select[tuple[UUID]]:
    """The tenant's shared spaces: no personal owner and a parent org space."""
    return sa.select(Spaces.id).where(
        Spaces.tenant_id == tenant_id,
        Spaces.user_id.is_(None),
        Spaces.tenant_space_id.is_not(None),
    )


def _space_ids(tenant_id: UUID, space_id: UUID) -> sa.Select[tuple[UUID]]:
    """One space of any kind, only when it belongs to the tenant."""
    return sa.select(Spaces.id).where(
        Spaces.id == space_id, Spaces.tenant_id == tenant_id
    )


def _scope(tenant_id: UUID, space_id: Optional[UUID]) -> sa.Select[tuple[UUID]]:
    if space_id is None:
        return _shared_space_ids(tenant_id)
    return _space_ids(tenant_id, space_id)


def _role(value: str) -> SpaceRoleValue:
    return SpaceRoleValue(value)


def _classification(
    id: Optional[UUID], name: Optional[str], level: Optional[int]
) -> Optional[OversightClassification]:
    if id is None or name is None or level is None:
        return None
    return OversightClassification(id=id, name=name, security_level=level)


def _model_ref(
    id: Optional[UUID],
    name: Optional[str],
    hosting: Optional[str],
    org: Optional[str],
) -> Optional[OversightModelRef]:
    if id is None or name is None:
        return None
    return OversightModelRef(id=id, name=name, hosting=hosting, org=org)


def _person(
    id: Optional[UUID], username: Optional[str], email: Optional[str]
) -> Optional[OversightPersonRef]:
    if id is None or email is None:
        return None
    return OversightPersonRef(id=id, name=username or email, email=email)


def _capabilities(purposes: Iterable[str]) -> list[Capability]:
    return sorted(cast(Capability, p) for p in set(purposes) if p in _CAPABILITIES)


def _member_state(state: Optional[str]) -> Literal["active", "invited", "inactive"]:
    if state == "active":
        return "active"
    if state == "invited":
        return "invited"
    return "inactive"


@dataclass(frozen=True)
class SharedSpaceRow:
    id: UUID
    name: str
    description: Optional[str]
    icon_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    data_retention_days: Optional[int]
    tenant_space_id: Optional[UUID]
    security_classification: Optional[OversightClassification]


@dataclass(frozen=True)
class SpaceSummaryRow:
    id: UUID
    name: str
    kind: SpaceKind
    security_classification: Optional[OversightClassification]


@dataclass(frozen=True)
class DirectMemberRow:
    user_id: UUID
    username: Optional[str]
    email: str
    state: Literal["active", "invited", "inactive"]
    role: SpaceRoleValue
    is_tenant_admin: bool
    oversight_joined_at: Optional[datetime]
    oversight_join_reason: Optional[str]

    @property
    def display_name(self) -> str:
        return self.username or self.email


@dataclass(frozen=True)
class GroupMemberRow:
    group_id: UUID
    name: str
    role: SpaceRoleValue
    user_count: int


@dataclass(frozen=True)
class SpaceMembership:
    """A space's live members, in display order, and the snapshot the
    oversight guards run on."""

    users: list[DirectMemberRow]
    groups: list[GroupMemberRow]
    snapshot: MembershipSnapshot
    # Manageable users of every admin group plus any extra group asked for.
    manageable_by_group: Mapping[UUID, frozenset[UUID]]

    def user(self, user_id: UUID) -> Optional[DirectMemberRow]:
        return next((row for row in self.users if row.user_id == user_id), None)

    def group(self, group_id: UUID) -> Optional[GroupMemberRow]:
        return next((row for row in self.groups if row.group_id == group_id), None)


@dataclass(frozen=True)
class MemberAggregate:
    member_count: int
    manageable_admins: int
    group_count: int


@dataclass(frozen=True)
class ViewerGroupRow:
    group_id: UUID
    name: str
    role: SpaceRoleValue


@dataclass(frozen=True)
class ViewerMembershipRows:
    direct: Mapping[UUID, tuple[SpaceRoleValue, Optional[datetime]]]
    groups: Mapping[UUID, list[ViewerGroupRow]]


@dataclass(frozen=True)
class SpaceBaseRow:
    id: UUID
    name: str
    description: Optional[str]
    icon_id: Optional[UUID]
    created_at: datetime
    security_classification: Optional[OversightClassification]


@dataclass(frozen=True)
class ResourceCountRow:
    assistants: int = 0
    apps: int = 0
    group_chats: int = 0
    knowledge_sources: int = 0


@dataclass(frozen=True)
class WidgetCountRow:
    active: int = 0
    paused: int = 0
    draft: int = 0
    awaiting_activation: int = 0


@dataclass(frozen=True)
class WidgetRequestRow:
    widget_id: UUID
    widget_name: str
    space: OversightRef
    requested_at: datetime
    requested_by: Optional[OversightPersonRef]


@dataclass(frozen=True)
class SpaceSettingsRows:
    completion_models: list[OversightModelRef]
    embedding_models: list[OversightModelRef]
    transcription_models: list[OversightModelRef]
    mcp_servers: list[OversightRef]
    capabilities: list[Capability]


@dataclass(frozen=True)
class KnowledgeLinkRow:
    assistant_id: UUID
    assistant_name: str
    source_id: UUID
    kind: Literal["collection", "website", "integration"]
    name: Optional[str]
    source_space_id: Optional[UUID]


@dataclass(frozen=True)
class AssistantConfig:
    assistant: AdminSpaceAssistant
    # General MCP servers that are switched on: what a widget visitor reaches.
    visitor_mcp_servers: list[OversightRef]


@dataclass(frozen=True)
class UsageCounts:
    questions: int
    app_runs: int
    active_users: int
    widget_questions: int


class SpaceOversightRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- gate -----------------------------------------------------------------

    async def shared_space(
        self, tenant_id: UUID, space_id: UUID, *, lock: bool = False
    ) -> SharedSpaceRow:
        """The shared space with this id in the tenant, or 404. Personal
        spaces, the organisation space and other tenants' spaces are
        indistinguishable from missing ones.

        ``lock`` takes ``FOR NO KEY UPDATE`` on the space row: oversight
        member writes serialise per space without blocking the foreign-key
        inserts other writers make (those take ``FOR KEY SHARE``).
        """
        stmt = (
            sa.select(
                Spaces.id,
                Spaces.name,
                Spaces.description,
                Spaces.icon_id,
                Spaces.created_at,
                Spaces.updated_at,
                Spaces.data_retention_days,
                Spaces.tenant_space_id,
                SecurityClassification.id,
                SecurityClassification.name,
                SecurityClassification.security_level,
            )
            .outerjoin(
                SecurityClassification,
                SecurityClassification.id == Spaces.security_classification_id,
            )
            .where(
                Spaces.id == space_id,
                Spaces.tenant_id == tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_not(None),
            )
        )
        if lock:
            stmt = stmt.with_for_update(key_share=True, of=Spaces)
        row = (await self.session.execute(stmt)).tuples().one_or_none()
        if row is None:
            raise NotFoundException("Space not found")
        (
            id,
            name,
            description,
            icon_id,
            created_at,
            updated_at,
            retention,
            tenant_space_id,
            sc_id,
            sc_name,
            sc_level,
        ) = row
        return SharedSpaceRow(
            id=id,
            name=name,
            description=description,
            icon_id=icon_id,
            created_at=created_at,
            updated_at=updated_at,
            data_retention_days=retention,
            tenant_space_id=tenant_space_id,
            security_classification=_classification(sc_id, sc_name, sc_level),
        )

    async def space_summary(
        self, tenant_id: UUID, space_id: UUID
    ) -> Optional[SpaceSummaryRow]:
        """Name, kind and classification of any space in the tenant."""
        stmt = (
            sa.select(
                Spaces.id,
                Spaces.name,
                Spaces.user_id,
                Spaces.tenant_space_id,
                SecurityClassification.id,
                SecurityClassification.name,
                SecurityClassification.security_level,
            )
            .outerjoin(
                SecurityClassification,
                SecurityClassification.id == Spaces.security_classification_id,
            )
            .where(Spaces.id == space_id, Spaces.tenant_id == tenant_id)
        )
        row = (await self.session.execute(stmt)).tuples().one_or_none()
        if row is None:
            return None
        id, name, owner_id, tenant_space_id, sc_id, sc_name, sc_level = row
        kind: SpaceKind
        if owner_id is not None:
            kind = "personal"
        elif tenant_space_id is None:
            kind = "organization"
        else:
            kind = "shared"
        return SpaceSummaryRow(
            id=id,
            name=name,
            kind=kind,
            security_classification=_classification(sc_id, sc_name, sc_level),
        )

    async def effective_role(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        user_id: UUID,
        group_ids: Collection[UUID],
    ) -> Optional[SpaceRoleValue]:
        """The user's role in any space of the tenant, as SpaceActor resolves
        it for a signed-in user: the owner of a personal space counts as
        admin, otherwise the higher of the direct and group roles."""
        direct = (
            sa.select(SpacesUsers.role)
            .where(SpacesUsers.space_id == Spaces.id, SpacesUsers.user_id == user_id)
            .scalar_subquery()
        )
        via_groups = (
            sa.select(sa.func.array_agg(SpacesUserGroups.role))
            .join(
                UserGroups,
                sa.and_(UserGroups.id == SpacesUserGroups.user_group_id, _live_group()),
            )
            .where(
                SpacesUserGroups.space_id == Spaces.id,
                SpacesUserGroups.user_group_id.in_(list(group_ids)),
            )
            .scalar_subquery()
        )
        stmt = sa.select(Spaces.user_id, direct, via_groups).where(
            Spaces.id == space_id, Spaces.tenant_id == tenant_id
        )
        row = (await self.session.execute(stmt)).tuples().one_or_none()
        if row is None:
            return None
        owner_id, direct_role, group_roles = row
        if owner_id is not None:
            return SpaceRoleValue.ADMIN if owner_id == user_id else None
        # Scalar subquery: None without a direct row.
        role = (
            _role(direct_role) if cast(Optional[str], direct_role) is not None else None
        )
        for group_role in cast(Optional[list[str]], group_roles) or []:
            role = higher_role(role, _role(group_role))
        return role

    # --- list -----------------------------------------------------------------

    async def list_shared_spaces(self, tenant_id: UUID) -> list[SpaceBaseRow]:
        stmt = (
            sa.select(
                Spaces.id,
                Spaces.name,
                Spaces.description,
                Spaces.icon_id,
                Spaces.created_at,
                SecurityClassification.id,
                SecurityClassification.name,
                SecurityClassification.security_level,
            )
            .outerjoin(
                SecurityClassification,
                SecurityClassification.id == Spaces.security_classification_id,
            )
            .where(Spaces.id.in_(_shared_space_ids(tenant_id)))
            .order_by(sa.func.lower(Spaces.name), Spaces.id)
        )
        rows = (await self.session.execute(stmt)).tuples().all()
        return [
            SpaceBaseRow(
                id=id,
                name=name,
                description=description,
                icon_id=icon_id,
                created_at=created_at,
                security_classification=_classification(sc_id, sc_name, sc_level),
            )
            for (
                id,
                name,
                description,
                icon_id,
                created_at,
                sc_id,
                sc_name,
                sc_level,
            ) in rows
        ]

    async def member_aggregates(
        self, tenant_id: UUID, space_id: Optional[UUID] = None
    ) -> dict[UUID, MemberAggregate]:
        """Distinct live members (direct or through live groups), manageable
        admins and live groups per space, aggregated in SQL: large groups
        across many spaces would otherwise stream every membership row."""
        scope = _scope(tenant_id, space_id)
        direct = (
            sa.select(
                SpacesUsers.space_id.label("space_id"),
                SpacesUsers.user_id.label("user_id"),
                SpacesUsers.role.label("role"),
                Users.state.label("state"),
            )
            .join(
                Users,
                sa.and_(Users.id == SpacesUsers.user_id, Users.deleted_at.is_(None)),
            )
            .where(SpacesUsers.space_id.in_(scope))
        )
        through_groups = (
            sa.select(
                SpacesUserGroups.space_id.label("space_id"),
                _UGU.c.user_id.label("user_id"),
                SpacesUserGroups.role.label("role"),
                Users.state.label("state"),
            )
            .join(
                UserGroups,
                sa.and_(UserGroups.id == SpacesUserGroups.user_group_id, _live_group()),
            )
            .join(_UGU, _UGU.c.user_group_id == SpacesUserGroups.user_group_id)
            .join(
                Users,
                sa.and_(Users.id == _UGU.c.user_id, Users.deleted_at.is_(None)),
            )
            .where(SpacesUserGroups.space_id.in_(scope))
        )
        effective = sa.union_all(direct, through_groups).subquery("effective")
        members = (
            sa.select(
                effective.c.space_id,
                sa.func.count(sa.distinct(effective.c.user_id)).label("member_count"),
                sa.func.count(sa.distinct(effective.c.user_id))
                .filter(
                    effective.c.role == SpaceRoleValue.ADMIN.value,
                    effective.c.state.in_(_MANAGEABLE_STATES),
                )
                .label("manageable_admins"),
            )
            .group_by(effective.c.space_id)
            .subquery("members")
        )
        groups = (
            sa.select(
                SpacesUserGroups.space_id,
                sa.func.count().label("group_count"),
            )
            .join(
                UserGroups,
                sa.and_(UserGroups.id == SpacesUserGroups.user_group_id, _live_group()),
            )
            .where(SpacesUserGroups.space_id.in_(scope))
            .group_by(SpacesUserGroups.space_id)
            .subquery("groups")
        )
        stmt = (
            sa.select(
                Spaces.id,
                members.c.member_count,
                members.c.manageable_admins,
                groups.c.group_count,
            )
            .outerjoin(members, members.c.space_id == Spaces.id)
            .outerjoin(groups, groups.c.space_id == Spaces.id)
            .where(Spaces.id.in_(scope))
        )
        rows = (await self.session.execute(stmt)).tuples().all()
        return {
            space: MemberAggregate(
                member_count=int(member_count or 0),
                manageable_admins=int(manageable_admins or 0),
                group_count=int(group_count or 0),
            )
            for space, member_count, manageable_admins, group_count in rows
        }

    async def admin_principals(
        self, tenant_id: UUID
    ) -> dict[UUID, list[AdminPrincipal]]:
        """Per shared space: admin users who can manage it, then admin groups
        with at least one such user, each by name."""
        scope = _shared_space_ids(tenant_id)
        users = (
            sa.select(
                SpacesUsers.space_id.label("space_id"),
                sa.literal("user").label("kind"),
                Users.id.label("id"),
                sa.func.coalesce(Users.username, Users.email).label("name"),
            )
            .join(Users, Users.id == SpacesUsers.user_id)
            .where(
                SpacesUsers.space_id.in_(scope),
                SpacesUsers.role == SpaceRoleValue.ADMIN.value,
                Users.deleted_at.is_(None),
                Users.state.in_(_MANAGEABLE_STATES),
            )
        )
        has_manageable_user = sa.exists(
            sa.select(sa.literal(1))
            .select_from(_UGU)
            .join(Users, Users.id == _UGU.c.user_id)
            .where(
                _UGU.c.user_group_id == UserGroups.id,
                Users.deleted_at.is_(None),
                Users.state.in_(_MANAGEABLE_STATES),
            )
        )
        groups = (
            sa.select(
                SpacesUserGroups.space_id.label("space_id"),
                sa.literal("group").label("kind"),
                UserGroups.id.label("id"),
                UserGroups.name.label("name"),
            )
            .join(UserGroups, UserGroups.id == SpacesUserGroups.user_group_id)
            .where(
                SpacesUserGroups.space_id.in_(scope),
                SpacesUserGroups.role == SpaceRoleValue.ADMIN.value,
                _live_group(),
                has_manageable_user,
            )
        )
        principals = sa.union_all(users, groups).subquery("principals")
        stmt = sa.select(
            principals.c.space_id,
            principals.c.kind,
            principals.c.id,
            principals.c.name,
        ).order_by(
            principals.c.space_id,
            sa.case((principals.c.kind == "user", 0), else_=1),
            sa.func.lower(principals.c.name),
        )
        result: dict[UUID, list[AdminPrincipal]] = defaultdict(list)
        for space, kind, id, name in (await self.session.execute(stmt)).tuples():
            result[space].append(
                AdminPrincipal(
                    kind=cast(Literal["user", "group"], kind), id=id, name=name
                )
            )
        return dict(result)

    async def viewer_memberships(
        self, tenant_id: UUID, *, user_id: UUID, group_ids: Collection[UUID]
    ) -> ViewerMembershipRows:
        """The viewer's own direct rows and live group rows in shared spaces."""
        scope = _shared_space_ids(tenant_id)
        direct_stmt = sa.select(
            SpacesUsers.space_id, SpacesUsers.role, SpacesUsers.oversight_joined_at
        ).where(SpacesUsers.space_id.in_(scope), SpacesUsers.user_id == user_id)
        direct_rows: dict[UUID, tuple[SpaceRoleValue, Optional[datetime]]] = {
            space: (_role(role), joined_at)
            for space, role, joined_at in (
                await self.session.execute(direct_stmt)
            ).tuples()
        }
        groups_stmt = (
            sa.select(
                SpacesUserGroups.space_id,
                UserGroups.id,
                UserGroups.name,
                SpacesUserGroups.role,
            )
            .join(
                UserGroups,
                sa.and_(UserGroups.id == SpacesUserGroups.user_group_id, _live_group()),
            )
            .where(
                SpacesUserGroups.space_id.in_(scope),
                SpacesUserGroups.user_group_id.in_(list(group_ids)),
            )
        )
        group_rows: dict[UUID, list[ViewerGroupRow]] = defaultdict(list)
        for space, group_id, name, role in (
            await self.session.execute(groups_stmt)
        ).tuples():
            group_rows[space].append(
                ViewerGroupRow(group_id=group_id, name=name, role=_role(role))
            )
        return ViewerMembershipRows(direct=direct_rows, groups=dict(group_rows))

    async def resource_counts(self, tenant_id: UUID) -> dict[UUID, ResourceCountRow]:
        scope = _shared_space_ids(tenant_id)

        def counted(kind: str, space_id: Any, *where: Any) -> sa.Select[Any]:
            return (
                sa.select(
                    space_id.label("space_id"),
                    sa.literal(kind).label("kind"),
                    sa.func.count().label("count"),
                )
                .where(space_id.in_(scope), *where)
                .group_by(space_id)
            )

        stmt = sa.union_all(
            counted(
                "assistants", Assistants.space_id, Assistants.is_default.is_(False)
            ),
            counted("apps", Apps.space_id),
            counted("group_chats", GroupChatsTable.space_id),
            counted("knowledge", CollectionsTable.space_id),
            counted("knowledge", Websites.space_id),
            counted("knowledge", IntegrationKnowledge.space_id),
        )
        totals: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for space, kind, count in (await self.session.execute(stmt)).tuples():
            totals[space][kind] += int(count)
        return {
            space: ResourceCountRow(
                assistants=counts["assistants"],
                apps=counts["apps"],
                group_chats=counts["group_chats"],
                knowledge_sources=counts["knowledge"],
            )
            for space, counts in totals.items()
        }

    async def widget_counts(self, tenant_id: UUID) -> dict[UUID, WidgetCountRow]:
        def with_status(status: WidgetStatus) -> Any:
            return sa.func.count().filter(Widgets.status == status.value)

        stmt = (
            sa.select(
                Widgets.space_id,
                with_status(WidgetStatus.ACTIVE),
                with_status(WidgetStatus.PAUSED),
                with_status(WidgetStatus.DRAFT),
                sa.func.count().filter(Widgets.activation_requested_at.is_not(None)),
            )
            .where(
                Widgets.tenant_id == tenant_id,
                Widgets.status != WidgetStatus.ARCHIVED.value,
                Widgets.space_id.in_(_shared_space_ids(tenant_id)),
            )
            .group_by(Widgets.space_id)
        )
        return {
            space: WidgetCountRow(
                active=int(active),
                paused=int(paused),
                draft=int(draft),
                awaiting_activation=int(awaiting),
            )
            for space, active, paused, draft, awaiting in (
                await self.session.execute(stmt)
            ).tuples()
        }

    async def last_activity(
        self, tenant_id: UUID, now: datetime, space_id: Optional[UUID] = None
    ) -> dict[UUID, datetime]:
        """The latest question or app run per space. The value is reduced to
        a bucket by the caller and never leaves the service."""
        scope = _scope(tenant_id, space_id)
        # One index probe per assistant (idx_questions_assistant_created).
        # No helper-run exclusion: help assistants live only in the
        # organisation space, which oversight never lists.
        latest_question = (
            sa.select(Questions.created_at)
            .where(Questions.assistant_id == Assistants.id)
            .order_by(Questions.created_at.desc())
            .limit(1)
            .lateral("latest_question")
        )
        questions = (
            sa.select(
                Assistants.space_id.label("space_id"),
                sa.func.max(latest_question.c.created_at).label("at"),
            )
            .select_from(Assistants)
            .join(latest_question, sa.true())
            .where(Assistants.space_id.in_(scope))
            .group_by(Assistants.space_id)
        )
        app_runs = (
            sa.select(
                Apps.space_id.label("space_id"),
                sa.func.max(AppRuns.created_at).label("at"),
            )
            .join(Apps, Apps.id == AppRuns.app_id)
            .where(
                AppRuns.tenant_id == tenant_id,
                AppRuns.created_at
                >= now - timedelta(days=APP_RUN_ACTIVITY_WINDOW_DAYS),
                Apps.space_id.in_(scope),
            )
            .group_by(Apps.space_id)
        )
        latest: dict[UUID, datetime] = {}
        for space, at in (
            await self.session.execute(sa.union_all(questions, app_runs))
        ).tuples():
            if space is None or at is None:
                continue
            if space not in latest or at > latest[space]:
                latest[space] = at
        return latest

    async def pending_widget_requests(self, tenant_id: UUID) -> list[WidgetRequestRow]:
        stmt = (
            sa.select(
                Widgets.id,
                Widgets.name,
                Widgets.activation_requested_at,
                Spaces.id,
                Spaces.name,
                Users.id,
                Users.username,
                Users.email,
            )
            .join(Spaces, Spaces.id == Widgets.space_id)
            .outerjoin(
                Users,
                sa.and_(
                    Users.id == Widgets.activation_requested_by_user_id,
                    Users.deleted_at.is_(None),
                ),
            )
            .where(
                Widgets.tenant_id == tenant_id,
                Spaces.tenant_id == tenant_id,
                Widgets.activation_requested_at.is_not(None),
            )
            .order_by(Widgets.activation_requested_at, Widgets.id)
        )
        result: list[WidgetRequestRow] = []
        for (
            widget_id,
            widget_name,
            requested_at,
            space_id,
            space_name,
            user_id,
            username,
            email,
        ) in (await self.session.execute(stmt)).tuples():
            assert requested_at is not None
            result.append(
                WidgetRequestRow(
                    widget_id=widget_id,
                    widget_name=widget_name,
                    space=OversightRef(id=space_id, name=space_name),
                    requested_at=requested_at,
                    requested_by=_person(user_id, username, email),
                )
            )
        return result

    # --- members --------------------------------------------------------------

    async def membership(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        extra_group_ids: Sequence[UUID] = (),
    ) -> SpaceMembership:
        """Live direct and group members of one space, plus the manageable
        users of its admin groups and of ``extra_group_ids``."""
        scope = _space_ids(tenant_id, space_id)
        users_stmt = (
            sa.select(
                SpacesUsers.user_id,
                Users.username,
                Users.email,
                Users.state,
                SpacesUsers.role,
                Users.id.in_(tenant_admin_user_ids_select(tenant_id)),
                SpacesUsers.oversight_joined_at,
                SpacesUsers.oversight_join_reason,
            )
            .join(Users, Users.id == SpacesUsers.user_id)
            .where(SpacesUsers.space_id.in_(scope), Users.deleted_at.is_(None))
            .order_by(
                sa.case((SpacesUsers.role == SpaceRoleValue.ADMIN.value, 0), else_=1),
                sa.func.lower(sa.func.coalesce(Users.username, Users.email)),
                SpacesUsers.user_id,
            )
        )
        users = [
            DirectMemberRow(
                user_id=user_id,
                username=username,
                email=email,
                state=_member_state(state),
                role=_role(role),
                is_tenant_admin=bool(is_tenant_admin),
                oversight_joined_at=joined_at,
                oversight_join_reason=reason,
            )
            for (
                user_id,
                username,
                email,
                state,
                role,
                is_tenant_admin,
                joined_at,
                reason,
            ) in (await self.session.execute(users_stmt)).tuples()
        ]

        live_users = (
            sa.select(sa.func.count())
            .select_from(_UGU)
            .join(Users, Users.id == _UGU.c.user_id)
            .where(_UGU.c.user_group_id == UserGroups.id, Users.deleted_at.is_(None))
            .correlate(UserGroups)
            .scalar_subquery()
        )
        groups_stmt = (
            sa.select(UserGroups.id, UserGroups.name, SpacesUserGroups.role, live_users)
            .join(
                UserGroups,
                sa.and_(UserGroups.id == SpacesUserGroups.user_group_id, _live_group()),
            )
            .where(SpacesUserGroups.space_id.in_(scope))
            .order_by(sa.func.lower(UserGroups.name), UserGroups.id)
        )
        groups = [
            GroupMemberRow(
                group_id=group_id, name=name, role=_role(role), user_count=int(count)
            )
            for group_id, name, role, count in (
                await self.session.execute(groups_stmt)
            ).tuples()
        ]

        admin_groups = sa.select(SpacesUserGroups.user_group_id).where(
            SpacesUserGroups.space_id.in_(scope),
            SpacesUserGroups.role == SpaceRoleValue.ADMIN.value,
        )
        wanted = _UGU.c.user_group_id.in_(admin_groups)
        if extra_group_ids:
            wanted = sa.or_(wanted, _UGU.c.user_group_id.in_(list(extra_group_ids)))
        manageable_stmt = (
            sa.select(_UGU.c.user_group_id, _UGU.c.user_id)
            .select_from(_UGU)
            .join(
                Users,
                sa.and_(
                    Users.id == _UGU.c.user_id,
                    Users.deleted_at.is_(None),
                    Users.state.in_(_MANAGEABLE_STATES),
                ),
            )
            .join(
                UserGroups,
                sa.and_(
                    UserGroups.id == _UGU.c.user_group_id,
                    UserGroups.tenant_id == tenant_id,
                    _live_group(),
                ),
            )
            .where(wanted)
        )
        by_group: dict[UUID, set[UUID]] = defaultdict(set)
        for group_id, user_id in (await self.session.execute(manageable_stmt)).tuples():
            by_group[group_id].add(user_id)
        manageable_by_group = {
            group_id: frozenset(ids) for group_id, ids in by_group.items()
        }

        snapshot = MembershipSnapshot(
            direct={
                row.user_id: DirectMembership(
                    role=row.role, manageable=row.state in MANAGEABLE_USER_STATES
                )
                for row in users
            },
            groups={
                row.group_id: GroupMembership(
                    role=row.role,
                    manageable_user_ids=manageable_by_group.get(
                        row.group_id, frozenset()
                    ),
                )
                for row in groups
            },
        )
        return SpaceMembership(
            users=users,
            groups=groups,
            snapshot=snapshot,
            manageable_by_group=manageable_by_group,
        )

    async def insert_member(
        self,
        space_id: UUID,
        user_id: UUID,
        role: SpaceRoleValue,
        *,
        oversight_joined_at: Optional[datetime] = None,
        oversight_join_reason: Optional[str] = None,
    ) -> bool:
        """False when the user already has a row."""
        stmt = (
            pg_insert(SpacesUsers)
            .values(
                space_id=space_id,
                user_id=user_id,
                role=role.value,
                oversight_joined_at=oversight_joined_at,
                oversight_join_reason=oversight_join_reason,
            )
            .on_conflict_do_nothing()
            .returning(SpacesUsers.user_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def update_member_role(
        self, space_id: UUID, user_id: UUID, role: SpaceRoleValue
    ) -> bool:
        stmt = (
            sa.update(SpacesUsers)
            .where(SpacesUsers.space_id == space_id, SpacesUsers.user_id == user_id)
            .values(role=role.value)
            .returning(SpacesUsers.user_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def delete_member(self, space_id: UUID, user_id: UUID) -> bool:
        stmt = (
            sa.delete(SpacesUsers)
            .where(SpacesUsers.space_id == space_id, SpacesUsers.user_id == user_id)
            .returning(SpacesUsers.role)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def insert_group(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> bool:
        """False when the group already has a row."""
        stmt = (
            pg_insert(SpacesUserGroups)
            .values(space_id=space_id, user_group_id=group_id, role=role.value)
            .on_conflict_do_nothing()
            .returning(SpacesUserGroups.user_group_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def update_group_role(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> bool:
        stmt = (
            sa.update(SpacesUserGroups)
            .where(
                SpacesUserGroups.space_id == space_id,
                SpacesUserGroups.user_group_id == group_id,
            )
            .values(role=role.value)
            .returning(SpacesUserGroups.user_group_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def delete_group(self, space_id: UUID, group_id: UUID) -> bool:
        stmt = (
            sa.delete(SpacesUserGroups)
            .where(
                SpacesUserGroups.space_id == space_id,
                SpacesUserGroups.user_group_id == group_id,
            )
            .returning(SpacesUserGroups.role)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def resource_ids(
        self, tenant_id: UUID, space_id: UUID
    ) -> tuple[list[UUID], list[UUID]]:
        """Assistant and app ids of the space, for scoped key revocation."""
        scope = _space_ids(tenant_id, space_id)
        stmt = sa.union_all(
            sa.select(sa.literal("assistant").label("kind"), Assistants.id).where(
                Assistants.space_id.in_(scope)
            ),
            sa.select(sa.literal("app").label("kind"), Apps.id).where(
                Apps.space_id.in_(scope)
            ),
        )
        assistants: list[UUID] = []
        apps: list[UUID] = []
        for kind, id in (await self.session.execute(stmt)).tuples():
            (assistants if kind == "assistant" else apps).append(id)
        return assistants, apps

    # --- detail ---------------------------------------------------------------

    async def settings(self, tenant_id: UUID, space_id: UUID) -> SpaceSettingsRows:
        scope = _space_ids(tenant_id, space_id)

        def models(
            kind: str, mapping: Any, model: Any, model_id: Any
        ) -> sa.Select[Any]:
            return (
                sa.select(
                    sa.literal(kind).label("kind"),
                    model.id.label("id"),
                    sa.func.coalesce(model.nickname, model.name).label("name"),
                    model.hosting.label("hosting"),
                    model.org.label("org"),
                    model.created_at.label("created_at"),
                )
                .select_from(mapping)
                .join(model, model.id == model_id)
                .where(mapping.space_id.in_(scope))
            )

        refs = sa.union_all(
            models(
                "completion",
                SpacesCompletionModels,
                CompletionModels,
                SpacesCompletionModels.completion_model_id,
            ),
            models(
                "embedding",
                SpacesEmbeddingModels,
                EmbeddingModels,
                SpacesEmbeddingModels.embedding_model_id,
            ),
            models(
                "transcription",
                SpacesTranscriptionModels,
                TranscriptionModels,
                SpacesTranscriptionModels.transcription_model_id,
            ),
        ).subquery("refs")
        by_kind: dict[str, list[OversightModelRef]] = defaultdict(list)
        for kind, id, name, hosting, org in (
            await self.session.execute(
                sa.select(
                    refs.c.kind, refs.c.id, refs.c.name, refs.c.hosting, refs.c.org
                ).order_by(refs.c.kind, refs.c.created_at, refs.c.id)
            )
        ).tuples():
            by_kind[kind].append(
                OversightModelRef(id=id, name=name, hosting=hosting, org=org)
            )

        mcp_stmt = (
            sa.select(MCPServers.id, MCPServers.name)
            .join(SpacesMCPServers, SpacesMCPServers.mcp_server_id == MCPServers.id)
            .where(
                SpacesMCPServers.space_id.in_(scope),
                MCPServers.purpose == "general",
            )
            .order_by(sa.func.lower(MCPServers.name), MCPServers.id)
        )
        mcp_servers = [
            OversightRef(id=id, name=name)
            for id, name in (await self.session.execute(mcp_stmt)).tuples()
        ]
        purposes = (
            await self.session.execute(
                sa.select(SpaceCapabilities.purpose).where(
                    SpaceCapabilities.space_id.in_(scope)
                )
            )
        ).scalars()
        return SpaceSettingsRows(
            completion_models=by_kind["completion"],
            embedding_models=by_kind["embedding"],
            transcription_models=by_kind["transcription"],
            mcp_servers=mcp_servers,
            capabilities=_capabilities(purposes),
        )

    async def widgets(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        target_ids: Optional[Sequence[UUID]] = None,
    ) -> list[AdminSpaceWidgetRef]:
        """Non-archived widgets of the space, optionally of some assistants."""
        stmt = (
            sa.select(
                Widgets.id,
                Widgets.name,
                Widgets.status,
                Widgets.activation_requested_at,
                Assistants.id,
                Assistants.name,
            )
            .outerjoin(
                Assistants,
                sa.and_(
                    Assistants.id == Widgets.target_id,
                    Assistants.space_id == Widgets.space_id,
                ),
            )
            .where(
                Widgets.tenant_id == tenant_id,
                Widgets.space_id.in_(_space_ids(tenant_id, space_id)),
                Widgets.status != WidgetStatus.ARCHIVED.value,
            )
            .order_by(sa.func.lower(Widgets.name), Widgets.id)
        )
        if target_ids is not None:
            stmt = stmt.where(Widgets.target_id.in_(list(target_ids)))
        return [
            AdminSpaceWidgetRef(
                id=id,
                name=name,
                status=WidgetStatus(status),
                # Outer join: None when the assistant no longer exists.
                assistant=(
                    OversightRef(id=assistant_id, name=assistant_name)
                    if cast(Optional[UUID], assistant_id) is not None
                    else None
                ),
                activation_requested_at=requested_at,
            )
            for id, name, status, requested_at, assistant_id, assistant_name in (
                await self.session.execute(stmt)
            ).tuples()
        ]

    def _assistant_ids(
        self,
        tenant_id: UUID,
        space_id: UUID,
        assistant_ids: Optional[Sequence[UUID]],
    ) -> sa.Select[tuple[UUID]]:
        stmt = sa.select(Assistants.id).where(
            Assistants.space_id.in_(_space_ids(tenant_id, space_id))
        )
        if assistant_ids is not None:
            stmt = stmt.where(Assistants.id.in_(list(assistant_ids)))
        return stmt

    async def knowledge_links(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        assistant_ids: Optional[Sequence[UUID]] = None,
    ) -> list[KnowledgeLinkRow]:
        """The knowledge each assistant of the space uses. OneDrive sources
        are personal folders: their names are never returned."""
        ids = self._assistant_ids(tenant_id, space_id, assistant_ids)
        collections = (
            sa.select(
                sa.literal("collection").label("kind"),
                AssistantsGroups.assistant_id.label("assistant_id"),
                Assistants.name.label("assistant_name"),
                CollectionsTable.id.label("source_id"),
                CollectionsTable.name.label("name"),
                CollectionsTable.space_id.label("source_space_id"),
            )
            .select_from(AssistantsGroups)
            .join(Assistants, Assistants.id == AssistantsGroups.assistant_id)
            .join(CollectionsTable, CollectionsTable.id == AssistantsGroups.group_id)
            .where(AssistantsGroups.assistant_id.in_(ids))
        )
        websites = (
            sa.select(
                sa.literal("website").label("kind"),
                AssistantsWebsites.assistant_id.label("assistant_id"),
                Assistants.name.label("assistant_name"),
                Websites.id.label("source_id"),
                sa.func.coalesce(Websites.name, Websites.url).label("name"),
                Websites.space_id.label("source_space_id"),
            )
            .select_from(AssistantsWebsites)
            .join(Assistants, Assistants.id == AssistantsWebsites.assistant_id)
            .join(Websites, Websites.id == AssistantsWebsites.website_id)
            .where(AssistantsWebsites.assistant_id.in_(ids))
        )
        integrations = (
            sa.select(
                sa.literal("integration").label("kind"),
                AssistantIntegrationKnowledge.assistant_id.label("assistant_id"),
                Assistants.name.label("assistant_name"),
                IntegrationKnowledge.id.label("source_id"),
                sa.case(
                    (IntegrationKnowledge.resource_type == "onedrive", sa.null()),
                    else_=IntegrationKnowledge.name,
                ).label("name"),
                IntegrationKnowledge.space_id.label("source_space_id"),
            )
            .select_from(AssistantIntegrationKnowledge)
            .join(
                Assistants, Assistants.id == AssistantIntegrationKnowledge.assistant_id
            )
            .join(
                IntegrationKnowledge,
                IntegrationKnowledge.id
                == AssistantIntegrationKnowledge.integration_knowledge_id,
            )
            .where(AssistantIntegrationKnowledge.assistant_id.in_(ids))
        )
        links = sa.union_all(collections, websites, integrations).subquery("links")
        stmt = sa.select(
            links.c.kind,
            links.c.assistant_id,
            links.c.assistant_name,
            links.c.source_id,
            links.c.name,
            links.c.source_space_id,
        ).order_by(
            links.c.assistant_id,
            links.c.kind,
            sa.func.lower(links.c.name),
            links.c.source_id,
        )
        return [
            KnowledgeLinkRow(
                assistant_id=assistant_id,
                assistant_name=assistant_name,
                source_id=source_id,
                kind=cast(Literal["collection", "website", "integration"], kind),
                name=name,
                source_space_id=source_space_id,
            )
            for (
                kind,
                assistant_id,
                assistant_name,
                source_id,
                name,
                source_space_id,
            ) in (await self.session.execute(stmt)).tuples()
        ]

    async def assistant_configs(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        assistant_ids: Optional[Sequence[UUID]] = None,
        widgets: Optional[Sequence[AdminSpaceWidgetRef]] = None,
        links: Optional[Sequence[KnowledgeLinkRow]] = None,
    ) -> list[AssistantConfig]:
        """Configuration of the space's assistants (or of some of them): the
        selected prompt, knowledge references, attachment count only, tools,
        flags and the widget serving each one. The default assistant is
        listed last. Pass ``widgets`` or ``links`` when already loaded."""
        ids = self._assistant_ids(tenant_id, space_id, assistant_ids)
        selected_prompt = (
            sa.select(Prompts.text)
            .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
            .where(
                PromptsAssistants.assistant_id == Assistants.id,
                PromptsAssistants.is_selected.is_(True),
            )
            .order_by(PromptsAssistants.created_at.desc())
            .limit(1)
            .correlate(Assistants)
            .scalar_subquery()
        )
        stmt = (
            sa.select(
                Assistants.id,
                Assistants.name,
                Assistants.description,
                Assistants.published,
                Assistants.is_default,
                Assistants.updated_at,
                Assistants.knowledge_mode,
                Assistants.insight_enabled,
                Assistants.logging_enabled,
                Assistants.data_retention_days,
                CompletionModels.id,
                sa.func.coalesce(CompletionModels.nickname, CompletionModels.name),
                CompletionModels.hosting,
                CompletionModels.org,
                selected_prompt,
            )
            .outerjoin(
                CompletionModels, CompletionModels.id == Assistants.completion_model_id
            )
            .where(Assistants.id.in_(ids))
            .order_by(
                Assistants.is_default,
                sa.func.lower(Assistants.name),
                Assistants.id,
            )
        )
        assistant_rows = (await self.session.execute(stmt)).tuples().all()
        if not assistant_rows:
            return []

        if links is None:
            links = await self.knowledge_links(
                tenant_id, space_id, assistant_ids=assistant_ids
            )
        knowledge: dict[UUID, list[OversightKnowledgeRef]] = defaultdict(list)
        for link in links:
            knowledge[link.assistant_id].append(
                OversightKnowledgeRef(
                    id=link.source_id,
                    name=link.name,
                    kind=link.kind,
                    from_organization=(
                        link.source_space_id is not None
                        and link.source_space_id != space_id
                    ),
                )
            )

        attachments = dict(
            (
                await self.session.execute(
                    sa.select(AssistantsFiles.assistant_id, sa.func.count())
                    .where(AssistantsFiles.assistant_id.in_(ids))
                    .group_by(AssistantsFiles.assistant_id)
                )
            )
            .tuples()
            .all()
        )

        mcp: dict[UUID, list[OversightRef]] = defaultdict(list)
        visitor_mcp: dict[UUID, list[OversightRef]] = defaultdict(list)
        for assistant_id, server_id, name, purpose, enabled in (
            await self.session.execute(
                sa.select(
                    AssistantMCPServers.assistant_id,
                    MCPServers.id,
                    MCPServers.name,
                    MCPServers.purpose,
                    MCPServers.is_enabled,
                )
                .join(MCPServers, MCPServers.id == AssistantMCPServers.mcp_server_id)
                .where(AssistantMCPServers.assistant_id.in_(ids))
                .order_by(sa.func.lower(MCPServers.name), MCPServers.id)
            )
        ).tuples():
            if purpose != "general":
                continue
            ref = OversightRef(id=server_id, name=name)
            mcp[assistant_id].append(ref)
            if enabled:
                visitor_mcp[assistant_id].append(ref)

        purposes: dict[UUID, list[str]] = defaultdict(list)
        for assistant_id, purpose in (
            await self.session.execute(
                sa.select(
                    AssistantCapabilities.assistant_id, AssistantCapabilities.purpose
                ).where(AssistantCapabilities.assistant_id.in_(ids))
            )
        ).tuples():
            purposes[assistant_id].append(purpose)

        if widgets is None:
            widgets = await self.widgets(
                tenant_id,
                space_id,
                target_ids=[row[0] for row in assistant_rows],
            )
        widget_by_assistant = {
            widget.assistant.id: widget
            for widget in widgets
            if widget.assistant is not None
        }

        configs: list[AssistantConfig] = []
        for (
            id,
            name,
            description,
            published,
            is_default,
            updated_at,
            knowledge_mode,
            insight_enabled,
            logging_enabled,
            retention,
            model_id,
            model_name,
            model_hosting,
            model_org,
            instructions,
        ) in assistant_rows:
            configs.append(
                AssistantConfig(
                    assistant=AdminSpaceAssistant(
                        id=id,
                        name=name,
                        description=description,
                        published=published,
                        is_default=is_default,
                        updated_at=updated_at,
                        completion_model=_model_ref(
                            model_id, model_name, model_hosting, model_org
                        ),
                        instructions=instructions,
                        knowledge_mode=(
                            "inject" if knowledge_mode == "inject" else "tool"
                        ),
                        knowledge=knowledge.get(id, []),
                        attachment_count=int(attachments.get(id, 0)),
                        mcp_servers=mcp.get(id, []),
                        capabilities=_capabilities(purposes.get(id, [])),
                        insight_enabled=insight_enabled,
                        logging_enabled=logging_enabled,
                        data_retention_days=retention,
                        widget=widget_by_assistant.get(id),
                    ),
                    visitor_mcp_servers=visitor_mcp.get(id, []),
                )
            )
        return configs

    async def apps(self, tenant_id: UUID, space_id: UUID) -> list[AdminSpaceApp]:
        scope = _space_ids(tenant_id, space_id)
        selected_prompt = (
            sa.select(Prompts.text)
            .join(AppsPrompts, AppsPrompts.prompt_id == Prompts.id)
            .where(AppsPrompts.app_id == Apps.id, AppsPrompts.is_selected.is_(True))
            .order_by(AppsPrompts.created_at.desc())
            .limit(1)
            .correlate(Apps)
            .scalar_subquery()
        )
        completion = aliased(CompletionModels)
        transcription = aliased(TranscriptionModels)
        stmt = (
            sa.select(
                Apps.id,
                Apps.name,
                Apps.description,
                Apps.published,
                Apps.data_retention_days,
                completion.id,
                sa.func.coalesce(completion.nickname, completion.name),
                completion.hosting,
                completion.org,
                transcription.id,
                sa.func.coalesce(transcription.nickname, transcription.name),
                transcription.hosting,
                transcription.org,
                selected_prompt,
            )
            .outerjoin(completion, completion.id == Apps.completion_model_id)
            .outerjoin(transcription, transcription.id == Apps.transcription_model_id)
            .where(Apps.space_id.in_(scope))
            .order_by(sa.func.lower(Apps.name), Apps.id)
        )
        return [
            AdminSpaceApp(
                id=id,
                name=name,
                description=description,
                published=published,
                completion_model=_model_ref(cm_id, cm_name, cm_hosting, cm_org),
                transcription_model=_model_ref(tm_id, tm_name, tm_hosting, tm_org),
                instructions=instructions,
                data_retention_days=retention,
            )
            for (
                id,
                name,
                description,
                published,
                retention,
                cm_id,
                cm_name,
                cm_hosting,
                cm_org,
                tm_id,
                tm_name,
                tm_hosting,
                tm_org,
                instructions,
            ) in (await self.session.execute(stmt)).tuples()
        ]

    async def group_chats(
        self, tenant_id: UUID, space_id: UUID
    ) -> list[AdminSpaceGroupChat]:
        assistant_count = (
            sa.select(sa.func.count())
            .select_from(GroupChatsAssistantsMapping)
            .where(GroupChatsAssistantsMapping.group_chat_id == GroupChatsTable.id)
            .correlate(GroupChatsTable)
            .scalar_subquery()
        )
        stmt = (
            sa.select(
                GroupChatsTable.id,
                GroupChatsTable.name,
                GroupChatsTable.published,
                GroupChatsTable.insight_enabled,
                assistant_count,
            )
            .where(GroupChatsTable.space_id.in_(_space_ids(tenant_id, space_id)))
            .order_by(sa.func.lower(GroupChatsTable.name), GroupChatsTable.id)
        )
        return [
            AdminSpaceGroupChat(
                id=id,
                name=name,
                published=published,
                insight_enabled=insight_enabled,
                assistant_count=int(count),
            )
            for id, name, published, insight_enabled, count in (
                await self.session.execute(stmt)
            ).tuples()
        ]

    async def knowledge_sources(
        self,
        tenant_id: UUID,
        space_id: UUID,
        *,
        source_ids: Optional[Sequence[UUID]] = None,
        links: Optional[Sequence[KnowledgeLinkRow]] = None,
    ) -> list[AdminSpaceKnowledgeSource]:
        """Sources the space owns, or the tenant's sources with the given ids,
        with active document counts and cached sizes. Names and titles of
        documents are content and never read; website credentials are never
        selected, only whether one is set."""
        if source_ids is not None and not source_ids:
            return []
        if links is None:
            links = await self.knowledge_links(tenant_id, space_id)
        used_by: dict[UUID, list[OversightRef]] = defaultdict(list)
        for link in links:
            used_by[link.source_id].append(
                OversightRef(id=link.assistant_id, name=link.assistant_name)
            )

        def which(table: Any) -> sa.ColumnElement[bool]:
            if source_ids is None:
                return table.space_id == space_id
            return table.id.in_(list(source_ids))

        def document_count(foreign_key: Any, table: Any) -> Any:
            return (
                sa.select(sa.func.count(InfoBlobs.id))
                .where(foreign_key == table.id, active_info_blob_version())
                .correlate(table)
                .scalar_subquery()
            )

        sources: list[AdminSpaceKnowledgeSource] = []

        collections = sa.select(
            CollectionsTable.id,
            CollectionsTable.name,
            CollectionsTable.size,
            CollectionsTable.updated_at,
            document_count(InfoBlobs.group_id, CollectionsTable),
        ).where(CollectionsTable.tenant_id == tenant_id, which(CollectionsTable))
        for id, name, size, updated_at, count in (
            await self.session.execute(collections)
        ).tuples():
            sources.append(
                AdminSpaceKnowledgeSource(
                    id=id,
                    name=name,
                    kind="collection",
                    item_count=int(count),
                    size_bytes=int(size or 0),
                    updated_at=updated_at,
                    requires_login=False,
                    auto_disabled=False,
                    used_by=used_by.get(id, []),
                )
            )

        websites = sa.select(
            Websites.id,
            sa.func.coalesce(Websites.name, Websites.url),
            Websites.url,
            Websites.size,
            Websites.last_crawled_at,
            Websites.update_interval,
            # Whether a login is configured, computed in SQL; the credential
            # columns themselves are never selected.
            Websites.http_auth_username.is_not(None),
            sa.and_(
                Websites.update_interval == "never",
                Websites.consecutive_failures >= _AUTO_DISABLE_FAILURES,
            ),
            document_count(InfoBlobs.website_id, Websites),
        ).where(Websites.tenant_id == tenant_id, which(Websites))
        for (
            id,
            name,
            url,
            size,
            crawled_at,
            interval,
            requires_login,
            auto_disabled,
            count,
        ) in (await self.session.execute(websites)).tuples():
            sources.append(
                AdminSpaceKnowledgeSource(
                    id=id,
                    name=name,
                    kind="website",
                    item_count=int(count),
                    size_bytes=int(size or 0),
                    updated_at=crawled_at,
                    website_url=url,
                    update_interval=(
                        cast(UpdateInterval, interval)
                        if interval in _UPDATE_INTERVALS
                        else None
                    ),
                    requires_login=bool(requires_login),
                    auto_disabled=bool(auto_disabled),
                    used_by=used_by.get(id, []),
                )
            )

        integrations = (
            sa.select(
                IntegrationKnowledge.id,
                IntegrationKnowledge.name,
                IntegrationKnowledge.resource_type,
                IntegrationKnowledge.size,
                IntegrationKnowledge.last_synced_at,
                Integration.integration_type,
                document_count(
                    InfoBlobs.integration_knowledge_id, IntegrationKnowledge
                ),
            )
            .outerjoin(
                UserIntegration,
                UserIntegration.id == IntegrationKnowledge.user_integration_id,
            )
            .outerjoin(
                TenantIntegration,
                TenantIntegration.id == UserIntegration.tenant_integration_id,
            )
            .outerjoin(Integration, Integration.id == TenantIntegration.integration_id)
            .where(
                IntegrationKnowledge.tenant_id == tenant_id,
                which(IntegrationKnowledge),
            )
        )
        for id, name, resource_type, size, synced_at, integration_type, count in (
            await self.session.execute(integrations)
        ).tuples():
            onedrive = resource_type == "onedrive"
            kind: Optional[IntegrationType] = None
            if onedrive:
                kind = "onedrive"
            elif integration_type in _INTEGRATION_TYPES:
                kind = cast(IntegrationType, integration_type)
            sources.append(
                AdminSpaceKnowledgeSource(
                    id=id,
                    name=None if onedrive else name,
                    kind="integration",
                    integration_type=kind,
                    item_count=int(count),
                    size_bytes=int(size or 0),
                    updated_at=synced_at,
                    requires_login=False,
                    auto_disabled=False,
                    used_by=used_by.get(id, []),
                )
            )
        return sources

    async def inherited_knowledge_count(
        self, tenant_id: UUID, space: SharedSpaceRow
    ) -> int:
        """Sources the space sees without owning them: the organisation
        space's own and those distributed to either space."""
        visible_from = effective_space_ids_for(space.id, space.tenant_space_id)

        def inherited(source: Any) -> Any:
            table = source.table
            return (
                sa.select(sa.func.count(sa.distinct(table.id)))
                .where(
                    table.tenant_id == tenant_id,
                    source.visible_to(visible_from),
                    sa.or_(table.space_id.is_(None), table.space_id != space.id),
                )
                .scalar_subquery()
            )

        total = await self.session.scalar(
            sa.select(
                inherited(COLLECTION_SOURCE)
                + inherited(WEBSITE_SOURCE)
                + inherited(INTEGRATION_KNOWLEDGE_SOURCE)
            )
        )
        return int(total or 0)

    async def usage(
        self, tenant_id: UUID, space_id: UUID, *, now: datetime
    ) -> UsageCounts:
        """Questions from signed-in users, app runs and distinct active users
        in the window, plus anonymous widget questions."""
        scope = _space_ids(tenant_id, space_id)
        since = now - timedelta(days=USAGE_WINDOW_DAYS)
        # No join to users: that would silently drop widget and API-key
        # sessions instead of filtering on the principal.
        questions = exclude_helper_run_sessions(
            sa.select(Questions.id.label("id"), Sessions.user_id.label("user_id"))
            .join(Sessions, Sessions.id == Questions.session_id)
            .where(
                Questions.tenant_id == tenant_id,
                Questions.assistant_id.in_(
                    sa.select(Assistants.id).where(Assistants.space_id.in_(scope))
                ),
                Questions.created_at >= since,
                Sessions.user_id.is_not(None),
            ),
            Questions.session_id,
        ).cte("window_questions")
        app_runs = (
            sa.select(AppRuns.id.label("id"), AppRuns.user_id.label("user_id"))
            .where(
                AppRuns.tenant_id == tenant_id,
                AppRuns.app_id.in_(sa.select(Apps.id).where(Apps.space_id.in_(scope))),
                AppRuns.created_at >= since,
            )
            .cte("window_app_runs")
        )
        active = sa.union(
            sa.select(questions.c.user_id),
            sa.select(app_runs.c.user_id).where(app_runs.c.user_id.is_not(None)),
        ).subquery("active_users")
        first_day = (now - timedelta(days=USAGE_WINDOW_DAYS - 1)).date()
        widget_questions = (
            sa.select(sa.func.coalesce(sa.func.sum(WidgetDailyUsage.questions), 0))
            .join(Widgets, Widgets.id == WidgetDailyUsage.widget_id)
            .where(
                Widgets.tenant_id == tenant_id,
                Widgets.space_id.in_(scope),
                WidgetDailyUsage.day >= first_day,
            )
            .scalar_subquery()
        )
        stmt = sa.select(
            sa.select(sa.func.count()).select_from(questions).scalar_subquery(),
            sa.select(sa.func.count()).select_from(app_runs).scalar_subquery(),
            sa.select(sa.func.count()).select_from(active).scalar_subquery(),
            widget_questions,
        )
        question_count, app_run_count, active_users, widget_count = (
            (await self.session.execute(stmt)).tuples().one()
        )
        return UsageCounts(
            questions=int(question_count or 0),
            app_runs=int(app_run_count or 0),
            active_users=int(active_users or 0),
            widget_questions=int(widget_count or 0),
        )
