# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Tenant-admin oversight of shared spaces.

A separate read model: it never goes through SpaceActor, so no admin bypass
can leak into the content paths the actor gates. Administrators see
configuration, members and coarse usage of every shared space, manage
members without joining, and reach content only by joining with a reason.
Every change is written with ``AuditService.log_required`` in the same
transaction, so a change without its audit entry never commits.
"""

from collections.abc import Collection, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import ApiKeyStateReasonCode
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.roles.permissions import Permission, validate_permission
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import (
    MANAGEABLE_USER_STATES,
    DirectMembership,
    GroupMembership,
    MembershipSnapshot,
    bucket_for,
    can_leave,
    count_if_enough_people,
    direct_role,
    effective_role,
    group_role,
    higher_role,
    highest_role,
    joinable_roles,
    leaves_without_admin,
    manageable_admin_ids,
    raises_role,
)
from eneo.spaces.oversight.exceptions import (
    SpaceAdminMustJoinError,
    SpaceAlreadyMemberError,
    SpaceLastAdminError,
    SpaceSelfAccessError,
)
from eneo.spaces.oversight.oversight_models import (
    AdminPrincipal,
    AdminSpaceAdmins,
    AdminSpaceDetail,
    AdminSpaceGroupMember,
    AdminSpaceList,
    AdminSpaceListItem,
    AdminSpaceMembers,
    AdminSpaceMembershipSummary,
    AdminSpaceOversightJoin,
    AdminSpaceResourceCounts,
    AdminSpaceSettings,
    AdminSpaceUsage,
    AdminSpaceUserMember,
    AdminSpaceViewerMembership,
    AdminSpaceWidgetCounts,
    AdminWidgetRequestRef,
    AttentionReason,
    OversightRef,
)
from eneo.spaces.oversight.oversight_repo import (
    ResourceCountRow,
    SharedSpaceRow,
    SpaceMembership,
    SpaceOversightRepo,
    WidgetCountRow,
)

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
    from eneo.spaces.oversight.visit_repo import OversightVisitRepo
    from eneo.user_groups.user_groups_repo import UserGroupsRepository
    from eneo.users.user import UserInDB
    from eneo.users.user_repo import UsersRepository

# Names in audit descriptions are clipped so the description stays within
# the 500 characters the audit worker accepts.
_NAME_LIMIT = 120


def _clip(name: str) -> str:
    return name if len(name) <= _NAME_LIMIT else name[: _NAME_LIMIT - 1] + "…"


def admins_of(membership: SpaceMembership) -> AdminSpaceAdmins:
    manageable = manageable_admin_ids(membership.snapshot)
    principals = [
        AdminPrincipal(kind="user", id=row.user_id, name=row.display_name)
        for row in membership.users
        if row.role == SpaceRoleValue.ADMIN and row.state in MANAGEABLE_USER_STATES
    ]
    principals.extend(
        AdminPrincipal(kind="group", id=row.group_id, name=row.name)
        for row in membership.groups
        if row.role == SpaceRoleValue.ADMIN
        and membership.manageable_by_group.get(row.group_id)
    )
    return AdminSpaceAdmins(
        manageable=bool(manageable), count=len(manageable), principals=principals
    )


def viewer_membership_of(
    membership: SpaceMembership, user_id: UUID, group_ids: Collection[UUID]
) -> AdminSpaceViewerMembership:
    """The viewer's own relation to a space, with what they may join or leave."""
    snapshot = membership.snapshot
    direct = direct_role(snapshot, user_id)
    via_groups = [row for row in membership.groups if row.group_id in group_ids]
    through_groups = highest_role(row.role for row in via_groups)
    own_row = membership.user(user_id)
    return AdminSpaceViewerMembership(
        role=higher_role(direct, through_groups),
        direct_role=direct,
        group_role=through_groups,
        via_groups=[OversightRef(id=row.group_id, name=row.name) for row in via_groups],
        oversight_joined_at=own_row.oversight_joined_at if own_row else None,
        joinable_roles=joinable_roles(direct, through_groups),
        can_leave=can_leave(snapshot, user_id),
    )


def members_of(
    membership: SpaceMembership,
    *,
    member_count: int,
    user_id: UUID,
    group_ids: Collection[UUID],
) -> AdminSpaceMembers:
    return AdminSpaceMembers(
        users=[
            AdminSpaceUserMember(
                id=row.user_id,
                username=row.username,
                email=row.email,
                role=row.role,
                state=row.state,
                is_tenant_admin=row.is_tenant_admin,
                oversight_join=(
                    AdminSpaceOversightJoin(
                        joined_at=row.oversight_joined_at,
                        reason=row.oversight_join_reason,
                    )
                    if row.oversight_joined_at is not None
                    and row.oversight_join_reason is not None
                    else None
                ),
            )
            for row in membership.users
        ],
        groups=[
            AdminSpaceGroupMember(
                id=row.group_id, name=row.name, role=row.role, user_count=row.user_count
            )
            for row in membership.groups
        ],
        member_count=member_count,
        group_count=len(membership.groups),
        admins=admins_of(membership),
        viewer_membership=viewer_membership_of(membership, user_id, group_ids),
    )


class SpaceOversightService:
    def __init__(
        self,
        user: "UserInDB",
        repo: SpaceOversightRepo,
        user_repo: "UsersRepository",
        user_groups_repo: "UserGroupsRepository",
        audit_service: "AuditService",
        api_key_scope_revoker: "ApiKeyScopeRevoker",
        visit_repo: "OversightVisitRepo",
    ) -> None:
        self.user = user
        self.repo = repo
        self.user_repo = user_repo
        self.user_groups_repo = user_groups_repo
        self.audit_service = audit_service
        self.api_key_scope_revoker = api_key_scope_revoker
        self.visit_repo = visit_repo

    # --- helpers ----------------------------------------------------------

    @property
    def _tenant_id(self) -> UUID:
        return self.user.tenant_id

    def _group_ids(self) -> frozenset[UUID]:
        return frozenset(self.user.user_groups_ids)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _require_admin(self) -> None:
        # The API-key guards on the mount are no-ops for session callers.
        validate_permission(self.user, Permission.ADMIN)

    async def _locked_space(self, space_id: UUID) -> SharedSpaceRow:
        self._require_admin()
        return await self.repo.shared_space(self._tenant_id, space_id, lock=True)

    def _actor_role(self, snapshot: MembershipSnapshot) -> Optional[SpaceRoleValue]:
        return effective_role(snapshot, self.user.id, self._group_ids())

    @staticmethod
    def _keep_an_admin(before: MembershipSnapshot, after: MembershipSnapshot) -> None:
        if leaves_without_admin(before, after):
            raise SpaceLastAdminError()

    def _refuse_self_escalation(
        self, group_id: UUID, before: MembershipSnapshot, after: MembershipSnapshot
    ) -> None:
        """A group change must not raise the actor's own role: content access
        is only gained through a join, with its marker and reason."""
        if group_id in self._group_ids() and raises_role(
            self._actor_role(before), self._actor_role(after)
        ):
            raise SpaceSelfAccessError()

    async def _members(self, space_id: UUID) -> AdminSpaceMembers:
        membership = await self.repo.membership(self._tenant_id, space_id)
        return await self._members_from(space_id, membership)

    async def _members_from(
        self, space_id: UUID, membership: SpaceMembership
    ) -> AdminSpaceMembers:
        aggregates = await self.repo.member_aggregates(self._tenant_id, space_id)
        aggregate = aggregates.get(space_id)
        return members_of(
            membership,
            member_count=aggregate.member_count if aggregate else 0,
            user_id=self.user.id,
            group_ids=self._group_ids(),
        )

    async def _revoke_keys(self, space_id: UUID, user_id: UUID, reason: str) -> int:
        assistant_ids, app_ids = await self.repo.resource_ids(self._tenant_id, space_id)
        # Revocation entries go in this transaction too: queued, they would
        # outlive a change the mandatory audit write rolls back.
        return await self.api_key_scope_revoker.revoke_member_keys(
            tenant_id=self._tenant_id,
            owner_user_id=user_id,
            space_id=space_id,
            assistant_ids=assistant_ids,
            app_ids=app_ids,
            reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
            reason_text=reason,
            audit_in_transaction=True,
        )

    def _oversight(self, snapshot: MembershipSnapshot) -> dict[str, Any]:
        """The actor's relation to the space before the action."""
        role = self._actor_role(snapshot)
        return {
            "actor_is_member": role is not None,
            "actor_role": role.value if role else None,
        }

    async def _audit(
        self,
        *,
        action: ActionType,
        space: SharedSpaceRow,
        description: str,
        extra: Mapping[str, object],
        changes: Optional[Mapping[str, object]] = None,
    ) -> None:
        await self.audit_service.log_required(
            tenant_id=self._tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.SPACE,
            entity_id=space.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=space,
                space=space,
                changes=changes,
                extra=extra,
            ),
        )

    @staticmethod
    def _member_snapshot(user_id: UUID, name: str, email: str) -> dict[str, str]:
        return {"id": str(user_id), "name": name, "email": email}

    # --- reads ------------------------------------------------------------

    async def list_spaces(self) -> AdminSpaceList:
        self._require_admin()
        tenant_id = self._tenant_id
        now = self._now()
        spaces = await self.repo.list_shared_spaces(tenant_id)
        aggregates = await self.repo.member_aggregates(tenant_id)
        principals = await self.repo.admin_principals(tenant_id)
        viewer = await self.repo.viewer_memberships(
            tenant_id, user_id=self.user.id, group_ids=self._group_ids()
        )
        resources = await self.repo.resource_counts(tenant_id)
        widgets = await self.repo.widget_counts(tenant_id)
        activity = await self.repo.last_activity(tenant_id)
        requests = await self.repo.pending_widget_requests(tenant_id)

        items: list[AdminSpaceListItem] = []
        for space in spaces:
            aggregate = aggregates.get(space.id)
            manageable_admins = aggregate.manageable_admins if aggregate else 0
            counts = resources.get(space.id, ResourceCountRow())
            widget_counts = widgets.get(space.id, WidgetCountRow())
            direct = viewer.direct.get(space.id)
            through_groups = highest_role(
                row.role for row in viewer.groups.get(space.id, [])
            )
            attention: list[AttentionReason] = []
            if manageable_admins == 0:
                attention.append("no_admin")
            if widget_counts.awaiting_activation > 0:
                attention.append("widget_activation_requested")
            items.append(
                AdminSpaceListItem(
                    id=space.id,
                    name=space.name,
                    description=space.description,
                    icon_id=space.icon_id,
                    created_at=space.created_at,
                    security_classification=space.security_classification,
                    member_count=aggregate.member_count if aggregate else 0,
                    group_count=aggregate.group_count if aggregate else 0,
                    admins=AdminSpaceAdmins(
                        manageable=manageable_admins > 0,
                        count=manageable_admins,
                        principals=principals.get(space.id, []),
                    ),
                    resources=AdminSpaceResourceCounts(
                        assistants=counts.assistants,
                        apps=counts.apps,
                        group_chats=counts.group_chats,
                        knowledge_sources=counts.knowledge_sources,
                    ),
                    widgets=AdminSpaceWidgetCounts(
                        active=widget_counts.active,
                        paused=widget_counts.paused,
                        draft=widget_counts.draft,
                        awaiting_activation=widget_counts.awaiting_activation,
                    ),
                    last_activity=bucket_for(activity.get(space.id), now),
                    viewer_membership=AdminSpaceMembershipSummary(
                        role=higher_role(direct[0] if direct else None, through_groups),
                        via_group_only=direct is None and through_groups is not None,
                        oversight_joined_at=direct[1] if direct else None,
                    ),
                    attention=attention,
                )
            )
        return AdminSpaceList(
            items=items,
            widget_requests=[
                AdminWidgetRequestRef(
                    widget_id=request.widget_id,
                    widget_name=request.widget_name,
                    space=request.space,
                    requested_at=request.requested_at,
                    requested_by=request.requested_by,
                )
                for request in requests
            ],
        )

    async def get_space(self, space_id: UUID) -> AdminSpaceDetail:
        self._require_admin()
        tenant_id = self._tenant_id
        now = self._now()
        space = await self.repo.shared_space(tenant_id, space_id)
        settings = await self.repo.settings(tenant_id, space_id)
        members = await self._members(space_id)
        widgets = await self.repo.widgets(tenant_id, space_id)
        links = await self.repo.knowledge_links(tenant_id, space_id)
        configs = await self.repo.assistant_configs(
            tenant_id, space_id, widgets=widgets, links=links
        )
        apps = await self.repo.apps(tenant_id, space_id)
        group_chats = await self.repo.group_chats(tenant_id, space_id)
        knowledge = await self.repo.knowledge_sources(tenant_id, space_id, links=links)
        inherited = await self.repo.inherited_knowledge_count(tenant_id, space)
        usage = await self.repo.usage(tenant_id, space_id, now=now)
        activity = await self.repo.last_activity(tenant_id, space_id)

        questions = count_if_enough_people(usage.questions, usage.question_users)
        app_runs = count_if_enough_people(usage.app_runs, usage.app_run_users)
        active_users = count_if_enough_people(usage.active_users, usage.active_users)
        attention: list[AttentionReason] = []
        if not members.admins.manageable:
            attention.append("no_admin")
        if any(widget.activation_requested_at is not None for widget in widgets):
            attention.append("widget_activation_requested")
        return AdminSpaceDetail(
            id=space.id,
            name=space.name,
            description=space.description,
            icon_id=space.icon_id,
            created_at=space.created_at,
            updated_at=space.updated_at,
            security_classification=space.security_classification,
            settings=AdminSpaceSettings(
                completion_models=settings.completion_models,
                embedding_models=settings.embedding_models,
                transcription_models=settings.transcription_models,
                mcp_servers=settings.mcp_servers,
                capabilities=settings.capabilities,
                data_retention_days=space.data_retention_days,
            ),
            usage=AdminSpaceUsage(
                suppressed=None in (questions, app_runs, active_users),
                questions=questions,
                app_runs=app_runs,
                active_users=active_users,
                widget_questions=(
                    usage.widget_questions if usage.has_been_public else None
                ),
                last_activity=bucket_for(activity.get(space_id), now),
                knowledge_bytes=sum(source.size_bytes for source in knowledge),
            ),
            assistants=[config.assistant for config in configs],
            apps=apps,
            group_chats=group_chats,
            knowledge=knowledge,
            inherited_knowledge_count=inherited,
            widgets=widgets,
            members=members,
            attention=attention,
        )

    # --- member management ------------------------------------------------

    async def add_member(
        self, space_id: UUID, user_id: UUID, role: SpaceRoleValue
    ) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        if user_id == self.user.id:
            raise SpaceSelfAccessError()
        target = await self.user_repo.get_user_by_id_and_tenant_id(
            user_id, self._tenant_id
        )
        if target is None:
            raise NotFoundException("User not found")
        membership = await self.repo.membership(self._tenant_id, space_id)
        if membership.user(user_id) is not None:
            raise SpaceAlreadyMemberError()
        # Content access for a tenant admin goes through their own join, with
        # its reason and the marker members see. A group that contains one is
        # still allowed: the group's other members are why it is added.
        if await self.repo.is_tenant_admin(self._tenant_id, user_id):
            raise SpaceAdminMustJoinError()
        if not await self.repo.insert_member(space_id, user_id, role):
            raise SpaceAlreadyMemberError()
        name = target.username or target.email
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_ADDED,
            space=space,
            description=(
                f"Added {_clip(name)} to space '{_clip(space.name)}' as"
                f" {role.value} (organisation administrator)"
            ),
            extra={
                "oversight": self._oversight(membership.snapshot),
                "member": self._member_snapshot(user_id, name, target.email),
                "role": role.value,
            },
        )
        return await self._members(space_id)

    async def change_member_role(
        self, space_id: UUID, user_id: UUID, role: SpaceRoleValue
    ) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        if user_id == self.user.id:
            raise SpaceSelfAccessError()
        membership = await self.repo.membership(self._tenant_id, space_id)
        member = membership.user(user_id)
        current = membership.snapshot.direct.get(user_id)
        if member is None or current is None:
            raise NotFoundException("Member not found")
        if current.role == role:
            return await self._members_from(space_id, membership)
        if member.is_tenant_admin and raises_role(current.role, role):
            raise SpaceAdminMustJoinError()
        before = membership.snapshot
        after = before.with_direct(
            user_id, DirectMembership(role=role, manageable=current.manageable)
        )
        self._keep_an_admin(before, after)
        if not await self.repo.update_member_role(space_id, user_id, role):
            raise NotFoundException("Member not found")
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_ROLE_CHANGED,
            space=space,
            description=(
                f"Changed role of {_clip(member.display_name)} in space"
                f" '{_clip(space.name)}' from {current.role.value} to"
                f" {role.value} (organisation administrator)"
            ),
            changes={"role": {"old": current.role.value, "new": role.value}},
            extra={
                "oversight": self._oversight(before),
                "member": self._member_snapshot(
                    user_id, member.display_name, member.email
                ),
            },
        )
        return await self._members(space_id)

    async def remove_member(self, space_id: UUID, user_id: UUID) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        if user_id == self.user.id:
            raise SpaceSelfAccessError()
        membership = await self.repo.membership(self._tenant_id, space_id)
        member = membership.user(user_id)
        if member is None:
            raise NotFoundException("Member not found")
        before = membership.snapshot
        self._keep_an_admin(before, before.with_direct(user_id, None))
        if not await self.repo.delete_member(space_id, user_id):
            raise NotFoundException("Member not found")
        await self.visit_repo.close(space_id, user_id, left_at=self._now())
        revoked = await self._revoke_keys(
            space_id, user_id, "Removed from space by an organisation administrator"
        )
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_REMOVED,
            space=space,
            description=(
                f"Removed {_clip(member.display_name)} from space"
                f" '{_clip(space.name)}' (organisation administrator)"
            ),
            extra={
                "oversight": self._oversight(before),
                "member": self._member_snapshot(
                    user_id, member.display_name, member.email
                ),
                "api_keys_revoked": revoked,
            },
        )
        return await self._members(space_id)

    async def add_group(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        group = await self.user_groups_repo.get_user_group(group_id)
        # The group repository has no tenant filter.
        if group is None or group.tenant_id != self._tenant_id:
            raise NotFoundException("Group not found")
        membership = await self.repo.membership(
            self._tenant_id, space_id, extra_group_ids=[group_id]
        )
        # Before the guards: they judge an after-state that replaces the row.
        if membership.group(group_id) is not None:
            raise SpaceAlreadyMemberError()
        before = membership.snapshot
        after = before.with_group(
            group_id,
            GroupMembership(
                role=role,
                manageable_user_ids=membership.manageable_by_group.get(
                    group_id, frozenset()
                ),
            ),
        )
        self._refuse_self_escalation(group_id, before, after)
        if not await self.repo.insert_group(space_id, group_id, role):
            raise SpaceAlreadyMemberError()
        members = await self.repo.membership(self._tenant_id, space_id)
        added = members.group(group_id)
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_ADDED,
            space=space,
            description=(
                f"Added {_clip(group.name)} to space '{_clip(space.name)}' as"
                f" {role.value} (organisation administrator)"
            ),
            extra={
                "oversight": self._oversight(before),
                "group": {
                    "id": str(group_id),
                    "name": group.name,
                    "user_count": added.user_count if added else 0,
                },
                "role": role.value,
            },
        )
        return await self._members_from(space_id, members)

    async def change_group_role(
        self, space_id: UUID, group_id: UUID, role: SpaceRoleValue
    ) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        membership = await self.repo.membership(
            self._tenant_id, space_id, extra_group_ids=[group_id]
        )
        group = membership.group(group_id)
        if group is None:
            raise NotFoundException("Group not found in this space")
        if group.role == role:
            return await self._members_from(space_id, membership)
        before = membership.snapshot
        after = before.with_group(
            group_id,
            GroupMembership(
                role=role,
                manageable_user_ids=membership.manageable_by_group.get(
                    group_id, frozenset()
                ),
            ),
        )
        self._refuse_self_escalation(group_id, before, after)
        self._keep_an_admin(before, after)
        if not await self.repo.update_group_role(space_id, group_id, role):
            raise NotFoundException("Group not found in this space")
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_ROLE_CHANGED,
            space=space,
            description=(
                f"Changed role of {_clip(group.name)} in space"
                f" '{_clip(space.name)}' from {group.role.value} to"
                f" {role.value} (organisation administrator)"
            ),
            changes={"role": {"old": group.role.value, "new": role.value}},
            extra={
                "oversight": self._oversight(before),
                "group": {
                    "id": str(group_id),
                    "name": group.name,
                    "user_count": group.user_count,
                },
            },
        )
        return await self._members(space_id)

    async def remove_group(self, space_id: UUID, group_id: UUID) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        membership = await self.repo.membership(self._tenant_id, space_id)
        group = membership.group(group_id)
        if group is None:
            raise NotFoundException("Group not found in this space")
        before = membership.snapshot
        self._keep_an_admin(before, before.with_group(group_id, None))
        # Keys of users who lose access through the group are not revoked,
        # as on the space members page.
        if not await self.repo.delete_group(space_id, group_id):
            raise NotFoundException("Group not found in this space")
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_MEMBER_REMOVED,
            space=space,
            description=(
                f"Removed {_clip(group.name)} from space"
                f" '{_clip(space.name)}' (organisation administrator)"
            ),
            extra={
                "oversight": self._oversight(before),
                "group": {
                    "id": str(group_id),
                    "name": group.name,
                    "user_count": group.user_count,
                },
            },
        )
        return await self._members(space_id)

    # --- join and leave ---------------------------------------------------

    async def join(
        self, space_id: UUID, role: SpaceRoleValue, reason: str
    ) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        membership = await self.repo.membership(self._tenant_id, space_id)
        snapshot = membership.snapshot
        if self.user.id in snapshot.direct:
            raise SpaceAlreadyMemberError()
        prior_group_role = group_role(snapshot, self._group_ids())
        if role not in joinable_roles(None, prior_group_role):
            raise BadRequestException(
                "Choose a role above the one you have through a group."
            )
        joined_at = self._now()
        if not await self.repo.insert_member(
            space_id,
            self.user.id,
            role,
            oversight_joined_at=joined_at,
            oversight_join_reason=reason,
        ):
            raise SpaceAlreadyMemberError()
        # The marker goes with the member row on leave; the visit stays for
        # the space's members to see.
        await self.visit_repo.open(
            tenant_id=self._tenant_id,
            space_id=space_id,
            user_id=self.user.id,
            role=role,
            reason=reason,
            joined_at=joined_at,
        )
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_JOINED,
            space=space,
            description=(
                f"Joined space '{_clip(space.name)}' as {role.value} through oversight"
            ),
            extra={
                "oversight": self._oversight(snapshot),
                "role": role.value,
                "reason": reason,
                "prior_group_role": (
                    prior_group_role.value if prior_group_role else None
                ),
            },
        )
        return await self._members(space_id)

    async def leave(self, space_id: UUID) -> AdminSpaceMembers:
        space = await self._locked_space(space_id)
        membership = await self.repo.membership(self._tenant_id, space_id)
        before = membership.snapshot
        own_row = membership.user(self.user.id)
        if own_row is None:
            raise BadRequestException("You have no direct membership in this space.")
        self._keep_an_admin(before, before.with_direct(self.user.id, None))
        # Never SpaceService.remove_member: it refuses to remove yourself.
        if not await self.repo.delete_member(space_id, self.user.id):
            raise BadRequestException("You have no direct membership in this space.")
        await self.visit_repo.close(space_id, self.user.id, left_at=self._now())
        revoked = await self._revoke_keys(space_id, self.user.id, "Left the space")
        remaining = group_role(before, self._group_ids())
        await self._audit(
            action=ActionType.SPACE_OVERSIGHT_LEFT,
            space=space,
            description=f"Left space '{_clip(space.name)}' (oversight)",
            extra={
                "oversight": self._oversight(before),
                "was_oversight_join": own_row.oversight_joined_at is not None,
                "remaining_group_role": remaining.value if remaining else None,
                "api_keys_revoked": revoked,
            },
        )
        return await self._members(space_id)
