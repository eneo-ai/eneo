from typing import TypeVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.skill_table import (
    AppSkillBindings,
    AssistantSkillBindings,
    GovernancePolicySkillBindings,
    SkillRevisions,
    Skills,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.main.models import Status
from eneo.skills.domain.skill import (
    PublishedSkill,
    PublishedSkillDeactivationError,
    PublishedSkillDeletionError,
    PublishedSkillSummary,
    ResolvedSkillBinding,
    Skill,
    SkillAdoptionCursor,
    SkillAdoptionDrift,
    SkillAdoptionPersonalChat,
    SkillAdoptionResource,
    SkillAdoptionResourceKind,
    SkillAdoptionRevisionCount,
    SkillAdoptionSummary,
    SkillBindingReference,
    SkillBindingSource,
    SkillCatalogEntry,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillPublicationChange,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionConflictError,
    SkillRevisionSummary,
    SkillSlugConflictError,
    SkillStatusChange,
    SkillSummary,
)

_BindingRow = TypeVar(
    "_BindingRow",
    AssistantSkillBindings,
    AppSkillBindings,
    GovernancePolicySkillBindings,
)
_SKILL_SLUG_CONSTRAINT = "uq_skills_space_id_slug"


def _is_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
    original = getattr(error, "orig", None)
    reported_name = getattr(original, "constraint_name", None)
    if reported_name == constraint_name:
        return True
    return constraint_name in str(original if original is not None else error)


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_CurrentSkillRevision = aliased(SkillRevisions, name="current_skill_revision")
_PublishedSkillRevision = aliased(SkillRevisions, name="published_skill_revision")


class SkillRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_revision(row: SkillRevisions) -> SkillRevision:
        return SkillRevision(
            id=row.id,
            skill_id=row.skill_id,
            revision_number=row.revision_number,
            display_name=row.display_name,
            description=row.description,
            instructions=row.instructions,
            content_digest=row.content_digest,
            created_by_user_id=row.created_by_user_id,
            created_at=row.created_at,
        )

    @classmethod
    def _to_skill(cls, row: Skills, revision: SkillRevisions) -> Skill:
        return Skill(
            id=row.id,
            space_id=row.space_id,
            slug=row.slug,
            is_active=row.is_active,
            current_revision_number=row.current_revision_number,
            created_by_user_id=row.created_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            current_revision=cls._to_revision(revision),
            published_revision_number=row.published_revision_number,
            first_published_at=row.first_published_at,
        )

    @staticmethod
    def _to_summary(
        *,
        skill: Skills,
        revision_id: UUID,
        display_name: str,
        description: str,
        content_digest: str,
    ) -> SkillSummary:
        return SkillSummary(
            id=skill.id,
            space_id=skill.space_id,
            slug=skill.slug,
            is_active=skill.is_active,
            current_revision_id=revision_id,
            current_revision_number=skill.current_revision_number,
            display_name=display_name,
            description=description,
            content_digest=content_digest,
            created_by_user_id=skill.created_by_user_id,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            published_revision_number=skill.published_revision_number,
            first_published_at=skill.first_published_at,
        )

    @staticmethod
    def _skill_query() -> sa.Select[tuple[Skills, SkillRevisions]]:
        return sa.select(Skills, SkillRevisions).join(
            SkillRevisions,
            sa.and_(
                SkillRevisions.skill_id == Skills.id,
                SkillRevisions.revision_number == Skills.current_revision_number,
            ),
        )

    @staticmethod
    def _catalog_predicates(
        *,
        space_id: UUID,
        query: str | None,
    ) -> list[ColumnElement[bool]]:
        predicates: list[ColumnElement[bool]] = [Skills.space_id == space_id]
        if query is not None:
            predicates.append(
                sa.or_(
                    Skills.slug.icontains(query, autoescape=True),
                    SkillRevisions.display_name.icontains(query, autoescape=True),
                    SkillRevisions.description.icontains(query, autoescape=True),
                )
            )
        return predicates

    @staticmethod
    def _organization_scope(tenant_id: UUID) -> tuple[ColumnElement[bool], ...]:
        return (
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )

    @staticmethod
    def _organization_adoption_facts(
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ):
        empty_space_id = sa.cast(sa.null(), AssistantSkillBindings.space_id.type)
        return sa.union_all(
            sa.select(
                sa.literal(SkillAdoptionResourceKind.ASSISTANT.value).label("kind"),
                AssistantSkillBindings.skill_revision_id.label("revision_id"),
                AssistantSkillBindings.space_id.label("space_id"),
            ).where(
                AssistantSkillBindings.tenant_id == tenant_id,
                AssistantSkillBindings.skill_id == skill_id,
            ),
            sa.select(
                sa.literal(SkillAdoptionResourceKind.APP.value).label("kind"),
                AppSkillBindings.skill_revision_id.label("revision_id"),
                AppSkillBindings.space_id.label("space_id"),
            ).where(
                AppSkillBindings.tenant_id == tenant_id,
                AppSkillBindings.skill_id == skill_id,
            ),
            sa.select(
                sa.literal("personal_chat").label("kind"),
                GovernancePolicySkillBindings.skill_revision_id.label("revision_id"),
                empty_space_id.label("space_id"),
            )
            .join(
                GovernancePolicies,
                GovernancePolicies.id == GovernancePolicySkillBindings.policy_id,
            )
            .where(
                GovernancePolicySkillBindings.tenant_id == tenant_id,
                GovernancePolicySkillBindings.skill_id == skill_id,
                GovernancePolicies.tenant_id == tenant_id,
                GovernancePolicies.scope
                == PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
            ),
        ).cte("organization_skill_adoption_facts")

    @staticmethod
    def _adoption_drift(
        *,
        revision_number: int,
        published_revision_number: int | None,
    ) -> SkillAdoptionDrift:
        if published_revision_number is None:
            return SkillAdoptionDrift.UNPUBLISHED
        if revision_number == published_revision_number:
            return SkillAdoptionDrift.CURRENT
        return SkillAdoptionDrift.BEHIND

    @staticmethod
    def _summary_query(
        *,
        published: bool,
    ):
        revision_number = (
            Skills.published_revision_number
            if published
            else Skills.current_revision_number
        )
        return (
            sa.select(
                Skills,
                SkillRevisions.id,
                SkillRevisions.display_name,
                SkillRevisions.description,
                SkillRevisions.content_digest,
            )
            .join(Spaces, Spaces.id == Skills.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == Skills.id,
                    SkillRevisions.revision_number == revision_number,
                ),
            )
        )

    async def create(
        self,
        *,
        space_id: UUID,
        slug: str,
        display_name: str,
        description: str,
        instructions: str,
        content_digest: str,
        created_by_user_id: UUID,
        is_active: bool = True,
    ) -> Skill:
        skill_id = uuid4()
        revision_id = uuid4()
        try:
            await self.session.execute(
                sa.insert(Skills).values(
                    id=skill_id,
                    space_id=space_id,
                    slug=slug,
                    is_active=is_active,
                    current_revision_number=1,
                    created_by_user_id=created_by_user_id,
                )
            )
        except IntegrityError as error:
            if _is_constraint_violation(error, _SKILL_SLUG_CONSTRAINT):
                raise SkillSlugConflictError from error
            raise
        await self.session.execute(
            sa.insert(SkillRevisions).values(
                id=revision_id,
                skill_id=skill_id,
                revision_number=1,
                display_name=display_name,
                description=description,
                instructions=instructions,
                content_digest=content_digest,
                created_by_user_id=created_by_user_id,
            )
        )
        skill = await self.get(skill_id=skill_id)
        assert skill is not None
        return skill

    async def get(self, *, skill_id: UUID) -> Skill | None:
        result = await self.session.execute(
            self._skill_query().where(Skills.id == skill_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return self._to_skill(row[0], row[1])

    async def list_catalog_entries(
        self,
        *,
        space_id: UUID,
        limit: int,
        after_slug: str | None,
        query: str | None,
    ) -> list[SkillCatalogEntry]:
        statement = (
            sa.select(
                Skills.id,
                Skills.space_id,
                Skills.slug,
                Skills.is_active,
                Skills.current_revision_number,
                Skills.created_by_user_id,
                Skills.created_at,
                Skills.updated_at,
                SkillRevisions.id.label("current_revision_id"),
                SkillRevisions.display_name,
                SkillRevisions.description,
                SkillRevisions.content_digest,
            )
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == Skills.id,
                    SkillRevisions.revision_number == Skills.current_revision_number,
                ),
            )
            .where(*self._catalog_predicates(space_id=space_id, query=query))
            .order_by(Skills.slug)
            .limit(limit)
        )
        if after_slug is not None:
            statement = statement.where(Skills.slug > after_slug)
        rows = await self.session.execute(statement)
        return [
            SkillCatalogEntry(
                id=skill_id,
                space_id=row_space_id,
                slug=slug,
                is_active=is_active,
                current_revision_number=current_revision_number,
                created_by_user_id=created_by_user_id,
                created_at=created_at,
                updated_at=updated_at,
                current_revision_id=current_revision_id,
                display_name=display_name,
                description=description,
                content_digest=content_digest,
            )
            for (
                skill_id,
                row_space_id,
                slug,
                is_active,
                current_revision_number,
                created_by_user_id,
                created_at,
                updated_at,
                current_revision_id,
                display_name,
                description,
                content_digest,
            ) in rows.tuples().all()
        ]

    async def count_catalog_entries(
        self,
        *,
        space_id: UUID,
        query: str | None,
    ) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(Skills)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == Skills.id,
                    SkillRevisions.revision_number == Skills.current_revision_number,
                ),
            )
            .where(*self._catalog_predicates(space_id=space_id, query=query))
        )
        return int(count or 0)

    async def list_organization_for_tenant(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after_slug: str | None,
        search: str | None = None,
    ) -> list[SkillSummary]:
        statement = (
            self._summary_query(published=False)
            .where(*self._organization_scope(tenant_id))
            .order_by(Skills.slug)
            .limit(limit)
        )
        if search:
            pattern = f"%{_escape_like_literal(search)}%"
            statement = statement.where(
                sa.or_(
                    Skills.slug.ilike(pattern, escape="\\"),
                    SkillRevisions.display_name.ilike(pattern, escape="\\"),
                    SkillRevisions.description.ilike(pattern, escape="\\"),
                )
            )
        if after_slug is not None:
            statement = statement.where(Skills.slug > after_slug)
        rows = await self.session.execute(statement)
        return [
            self._to_summary(
                skill=skill,
                revision_id=revision_id,
                display_name=display_name,
                description=description,
                content_digest=content_digest,
            )
            for (
                skill,
                revision_id,
                display_name,
                description,
                content_digest,
            ) in rows.tuples()
        ]

    async def get_organization_for_tenant(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> Skill | None:
        result = await self.session.execute(
            self._skill_query()
            .join(Spaces, Spaces.id == Skills.space_id)
            .where(
                Skills.id == skill_id,
                *self._organization_scope(tenant_id),
            )
        )
        row = result.one_or_none()
        return self._to_skill(row[0], row[1]) if row is not None else None

    async def get_organization_adoption_summary(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        published_revision_number: int | None,
    ) -> SkillAdoptionSummary:
        facts = self._organization_adoption_facts(
            tenant_id=tenant_id,
            skill_id=skill_id,
        )
        revision_rows = await self.session.execute(
            sa.select(
                facts.c.revision_id,
                SkillRevisions.revision_number,
                sa.func.count()
                .filter(facts.c.kind == SkillAdoptionResourceKind.ASSISTANT.value)
                .label("assistant_count"),
                sa.func.count()
                .filter(facts.c.kind == SkillAdoptionResourceKind.APP.value)
                .label("app_count"),
                sa.func.bool_or(facts.c.kind == "personal_chat").label(
                    "personal_chat_pinned"
                ),
            )
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.id == facts.c.revision_id,
                    SkillRevisions.skill_id == skill_id,
                ),
            )
            .group_by(facts.c.revision_id, SkillRevisions.revision_number)
            .order_by(SkillRevisions.revision_number)
        )
        revision_counts: list[SkillAdoptionRevisionCount] = []
        personal_chat: SkillAdoptionPersonalChat | None = None
        for (
            revision_id,
            revision_number,
            assistant_count,
            app_count,
            personal_chat_pinned,
        ) in revision_rows.tuples():
            revision_counts.append(
                SkillAdoptionRevisionCount(
                    revision_id=revision_id,
                    revision_number=revision_number,
                    assistant_count=int(assistant_count),
                    app_count=int(app_count),
                    personal_chat_pinned=bool(personal_chat_pinned),
                )
            )
            if personal_chat_pinned:
                personal_chat = SkillAdoptionPersonalChat(
                    revision_id=revision_id,
                    revision_number=revision_number,
                    drift=self._adoption_drift(
                        revision_number=revision_number,
                        published_revision_number=published_revision_number,
                    ),
                )

        behind_predicate: ColumnElement[bool]
        if published_revision_number is None:
            behind_predicate = sa.false()
        else:
            behind_predicate = (
                SkillRevisions.revision_number != published_revision_number
            )
        totals = (
            await self.session.execute(
                sa.select(
                    sa.func.count()
                    .filter(facts.c.kind == SkillAdoptionResourceKind.ASSISTANT.value)
                    .label("assistant_count"),
                    sa.func.count()
                    .filter(facts.c.kind == SkillAdoptionResourceKind.APP.value)
                    .label("app_count"),
                    sa.func.count(sa.distinct(facts.c.space_id))
                    .filter(
                        facts.c.kind.in_(
                            (
                                SkillAdoptionResourceKind.ASSISTANT.value,
                                SkillAdoptionResourceKind.APP.value,
                            )
                        )
                    )
                    .label("distinct_space_count"),
                    sa.func.count()
                    .filter(behind_predicate)
                    .label("behind_published_count"),
                )
                .select_from(facts)
                .join(
                    SkillRevisions,
                    sa.and_(
                        SkillRevisions.id == facts.c.revision_id,
                        SkillRevisions.skill_id == skill_id,
                    ),
                )
            )
        ).one()
        return SkillAdoptionSummary(
            assistant_count=int(totals.assistant_count),
            app_count=int(totals.app_count),
            distinct_space_count=int(totals.distinct_space_count),
            behind_published_count=int(totals.behind_published_count),
            personal_chat=personal_chat,
            revision_counts=tuple(revision_counts),
        )

    async def list_organization_adoption_resources(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        published_revision_number: int | None,
        limit: int,
        after: SkillAdoptionCursor | None,
    ) -> list[SkillAdoptionResource]:
        resources = sa.union_all(
            sa.select(
                sa.literal(0).label("kind_rank"),
                sa.literal(SkillAdoptionResourceKind.ASSISTANT.value).label("kind"),
                Assistants.id.label("resource_id"),
                Assistants.name.label("name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                SkillRevisions.id.label("revision_id"),
                SkillRevisions.revision_number.label("revision_number"),
            )
            .select_from(AssistantSkillBindings)
            .join(
                Assistants,
                Assistants.id == AssistantSkillBindings.assistant_id,
            )
            .join(Spaces, Spaces.id == AssistantSkillBindings.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.id == AssistantSkillBindings.skill_revision_id,
                    SkillRevisions.skill_id == skill_id,
                ),
            )
            .where(
                AssistantSkillBindings.tenant_id == tenant_id,
                AssistantSkillBindings.skill_id == skill_id,
                Spaces.tenant_id == tenant_id,
            ),
            sa.select(
                sa.literal(1).label("kind_rank"),
                sa.literal(SkillAdoptionResourceKind.APP.value).label("kind"),
                Apps.id.label("resource_id"),
                Apps.name.label("name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                SkillRevisions.id.label("revision_id"),
                SkillRevisions.revision_number.label("revision_number"),
            )
            .select_from(AppSkillBindings)
            .join(Apps, Apps.id == AppSkillBindings.app_id)
            .join(Spaces, Spaces.id == AppSkillBindings.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.id == AppSkillBindings.skill_revision_id,
                    SkillRevisions.skill_id == skill_id,
                ),
            )
            .where(
                AppSkillBindings.tenant_id == tenant_id,
                AppSkillBindings.skill_id == skill_id,
                Apps.tenant_id == tenant_id,
                Spaces.tenant_id == tenant_id,
            ),
        ).subquery("organization_skill_adoption_resources")
        statement = (
            sa.select(resources)
            .order_by(resources.c.kind_rank, resources.c.resource_id)
            .limit(limit)
        )
        if after is not None:
            after_rank = 0 if after.kind is SkillAdoptionResourceKind.ASSISTANT else 1
            statement = statement.where(
                sa.or_(
                    resources.c.kind_rank > after_rank,
                    sa.and_(
                        resources.c.kind_rank == after_rank,
                        resources.c.resource_id > after.resource_id,
                    ),
                )
            )
        rows = await self.session.execute(statement)
        return [
            SkillAdoptionResource(
                kind=SkillAdoptionResourceKind(kind),
                resource_id=resource_id,
                name=name,
                space_id=space_id,
                space_name=space_name,
                revision_id=revision_id,
                revision_number=revision_number,
                drift=self._adoption_drift(
                    revision_number=revision_number,
                    published_revision_number=published_revision_number,
                ),
            )
            for (
                _kind_rank,
                kind,
                resource_id,
                name,
                space_id,
                space_name,
                revision_id,
                revision_number,
            ) in rows.tuples()
        ]

    async def list_published_for_tenant(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after_slug: str | None,
        search: str | None = None,
    ) -> list[PublishedSkillSummary]:
        query = (
            self._summary_query(published=True)
            .where(
                *self._organization_scope(tenant_id),
                Skills.published_revision_number.is_not(None),
                Skills.is_active.is_(True),
            )
            .order_by(Skills.slug)
            .limit(limit)
        )
        if search:
            pattern = f"%{_escape_like_literal(search)}%"
            query = query.where(
                sa.or_(
                    Skills.slug.ilike(pattern, escape="\\"),
                    SkillRevisions.display_name.ilike(pattern, escape="\\"),
                    SkillRevisions.description.ilike(pattern, escape="\\"),
                )
            )
        if after_slug is not None:
            query = query.where(Skills.slug > after_slug)
        rows = await self.session.execute(query)
        summaries: list[PublishedSkillSummary] = []
        for (
            skill,
            revision_id,
            display_name,
            description,
            content_digest,
        ) in rows.tuples():
            assert skill.published_revision_number is not None
            assert skill.first_published_at is not None
            summaries.append(
                PublishedSkillSummary(
                    id=skill.id,
                    slug=skill.slug,
                    revision_id=revision_id,
                    revision_number=skill.published_revision_number,
                    display_name=display_name,
                    description=description,
                    content_digest=content_digest,
                    first_published_at=skill.first_published_at,
                )
            )
        return summaries

    async def get_published_for_tenant(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> PublishedSkill | None:
        result = await self.session.execute(
            sa.select(Skills, SkillRevisions)
            .join(Spaces, Spaces.id == Skills.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == Skills.id,
                    SkillRevisions.revision_number == Skills.published_revision_number,
                ),
            )
            .where(
                Skills.id == skill_id,
                *self._organization_scope(tenant_id),
                Skills.published_revision_number.is_not(None),
                Skills.is_active.is_(True),
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        skill, revision = row
        assert skill.published_revision_number is not None
        assert skill.first_published_at is not None
        return PublishedSkill(
            summary=PublishedSkillSummary(
                id=skill.id,
                slug=skill.slug,
                revision_id=revision.id,
                revision_number=skill.published_revision_number,
                display_name=revision.display_name,
                description=revision.description,
                content_digest=revision.content_digest,
                first_published_at=skill.first_published_at,
            ),
            revision=self._to_revision(revision),
        )

    async def get_revision(
        self, *, skill_id: UUID, revision_id: UUID
    ) -> SkillRevision | None:
        row = await self.session.scalar(
            sa.select(SkillRevisions).where(
                SkillRevisions.skill_id == skill_id,
                SkillRevisions.id == revision_id,
            )
        )
        return self._to_revision(row) if row is not None else None

    async def list_revision_summaries(
        self,
        *,
        skill_id: UUID,
        limit: int,
        before_revision_number: int | None,
    ) -> list[SkillRevisionSummary]:
        query = (
            sa.select(
                SkillRevisions.id,
                SkillRevisions.skill_id,
                SkillRevisions.revision_number,
                SkillRevisions.display_name,
                SkillRevisions.created_at,
            )
            .where(SkillRevisions.skill_id == skill_id)
            .order_by(SkillRevisions.revision_number.desc())
            .limit(limit)
        )
        if before_revision_number is not None:
            query = query.where(SkillRevisions.revision_number < before_revision_number)
        rows = await self.session.execute(query)
        return [
            SkillRevisionSummary(
                id=revision_id,
                skill_id=row_skill_id,
                revision_number=revision_number,
                display_name=display_name,
                created_at=created_at,
            )
            for (
                revision_id,
                row_skill_id,
                revision_number,
                display_name,
                created_at,
            ) in rows.tuples()
        ]

    async def count_revisions(self, *, skill_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(SkillRevisions)
            .where(SkillRevisions.skill_id == skill_id)
        )
        return int(count or 0)

    async def create_revision(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
        content_digest: str,
        created_by_user_id: UUID,
        expected_current_revision_id: UUID | None = None,
    ) -> SkillRevisionChange | None:
        skill_row = await self.session.scalar(
            sa.select(Skills).where(Skills.id == skill_id).with_for_update()
        )
        if skill_row is None:
            return None
        current_row = await self.session.scalar(
            sa.select(SkillRevisions).where(
                SkillRevisions.skill_id == skill_id,
                SkillRevisions.revision_number == skill_row.current_revision_number,
            )
        )
        if current_row is None:
            raise RuntimeError("Skill current revision is missing")
        if (
            expected_current_revision_id is not None
            and current_row.id != expected_current_revision_id
        ):
            raise SkillRevisionConflictError
        previous_revision_number = current_row.revision_number
        if (
            current_row.display_name == display_name
            and current_row.description == description
            and current_row.instructions == instructions
            and current_row.content_digest == content_digest
        ):
            return SkillRevisionChange(
                skill=self._to_skill(skill_row, current_row),
                revision=self._to_revision(current_row),
                created=False,
                previous_revision_number=previous_revision_number,
            )

        next_revision = skill_row.current_revision_number + 1
        revision_id = uuid4()
        await self.session.execute(
            sa.insert(SkillRevisions).values(
                id=revision_id,
                skill_id=skill_id,
                revision_number=next_revision,
                display_name=display_name,
                description=description,
                instructions=instructions,
                content_digest=content_digest,
                created_by_user_id=created_by_user_id,
            )
        )
        await self.session.execute(
            sa.update(Skills)
            .where(Skills.id == skill_id)
            .values(current_revision_number=next_revision, updated_at=sa.func.now())
        )
        skill = await self.get(skill_id=skill_id)
        if skill is None or skill.current_revision.id != revision_id:
            raise RuntimeError("New Skill revision was not persisted as current")
        return SkillRevisionChange(
            skill=skill,
            revision=skill.current_revision,
            created=True,
            previous_revision_number=previous_revision_number,
        )

    async def set_active(
        self, *, skill_id: UUID, is_active: bool
    ) -> SkillStatusChange | None:
        skill_row = await self.session.scalar(
            sa.select(Skills).where(Skills.id == skill_id).with_for_update()
        )
        if skill_row is None:
            return None
        return await self._set_active_on_locked_skill(
            skill_row=skill_row,
            is_active=is_active,
        )

    async def _set_active_on_locked_skill(
        self,
        *,
        skill_row: Skills,
        is_active: bool,
    ) -> SkillStatusChange:
        if not is_active and skill_row.published_revision_number is not None:
            raise PublishedSkillDeactivationError
        previous_is_active = skill_row.is_active
        changed = previous_is_active != is_active
        if changed:
            await self.session.execute(
                sa.update(Skills)
                .where(Skills.id == skill_row.id)
                .values(is_active=is_active, updated_at=sa.func.now())
            )
        skill = await self.get(skill_id=skill_row.id)
        if skill is None:
            raise RuntimeError("Locked Skill disappeared during status update")
        return SkillStatusChange(
            skill=skill,
            changed=changed,
            previous_is_active=previous_is_active,
        )

    async def _lock_organization_skill(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> Skills | None:
        return await self.session.scalar(
            sa.select(Skills)
            .join(Spaces, Spaces.id == Skills.space_id)
            .where(
                Skills.id == skill_id,
                *self._organization_scope(tenant_id),
            )
            .with_for_update(of=Skills)
        )

    async def publish_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        expected_revision_id: UUID,
    ) -> SkillPublicationChange | None:
        skill_row = await self._lock_organization_skill(
            tenant_id=tenant_id,
            skill_id=skill_id,
        )
        if skill_row is None:
            return None
        current_revision_id = await self.session.scalar(
            sa.select(SkillRevisions.id).where(
                SkillRevisions.skill_id == skill_id,
                SkillRevisions.revision_number == skill_row.current_revision_number,
            )
        )
        if current_revision_id != expected_revision_id:
            raise SkillRevisionConflictError

        previous = skill_row.published_revision_number
        previous_is_active = skill_row.is_active
        changed = previous != skill_row.current_revision_number
        if changed:
            await self.session.execute(
                sa.update(Skills)
                .where(Skills.id == skill_id)
                .values(
                    is_active=True,
                    published_revision_number=skill_row.current_revision_number,
                    first_published_at=sa.func.coalesce(
                        Skills.first_published_at,
                        sa.func.now(),
                    ),
                    updated_at=sa.func.now(),
                )
            )
        skill = await self.get(skill_id=skill_id)
        if skill is None:
            raise RuntimeError("Locked Skill disappeared during publication")
        return SkillPublicationChange(
            skill=skill,
            changed=changed,
            previous_published_revision_number=previous,
            previous_is_active=previous_is_active,
        )

    async def unpublish_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> SkillPublicationChange | None:
        skill_row = await self._lock_organization_skill(
            tenant_id=tenant_id,
            skill_id=skill_id,
        )
        if skill_row is None:
            return None
        previous = skill_row.published_revision_number
        previous_is_active = skill_row.is_active
        changed = previous is not None
        if changed:
            await self.session.execute(
                sa.update(Skills)
                .where(Skills.id == skill_id)
                .values(
                    is_active=False,
                    published_revision_number=None,
                    updated_at=sa.func.now(),
                )
            )
        skill = await self.get(skill_id=skill_id)
        if skill is None:
            raise RuntimeError("Locked Skill disappeared during unpublication")
        return SkillPublicationChange(
            skill=skill,
            changed=changed,
            previous_published_revision_number=previous,
            previous_is_active=previous_is_active,
        )

    async def delete(self, *, skill_id: UUID) -> Skill | None:
        result = await self.session.execute(
            self._skill_query().where(Skills.id == skill_id).with_for_update(of=Skills)
        )
        row = result.one_or_none()
        if row is None:
            return None
        skill = self._to_skill(row[0], row[1])
        return await self._delete_locked_skill(skill=skill)

    async def delete_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> Skill | None:
        skill_row = await self._lock_organization_skill(
            tenant_id=tenant_id,
            skill_id=skill_id,
        )
        if skill_row is None:
            return None
        revision_row = await self.session.scalar(
            sa.select(SkillRevisions).where(
                SkillRevisions.skill_id == skill_id,
                SkillRevisions.revision_number == skill_row.current_revision_number,
            )
        )
        if revision_row is None:
            raise RuntimeError("Skill current revision is missing")
        return await self._delete_locked_skill(
            skill=self._to_skill(skill_row, revision_row)
        )

    async def _delete_locked_skill(self, *, skill: Skill) -> Skill:
        if skill.first_published_at is not None:
            raise PublishedSkillDeletionError
        if await self._is_bound(skill_id=skill.id):
            raise SkillHasBindingsError
        if await self._has_nonterminal_app_run(skill_id=skill.id):
            raise SkillHasActiveAppRunsError
        try:
            await self.session.execute(sa.delete(Skills).where(Skills.id == skill.id))
        except IntegrityError as error:
            raise SkillHasBindingsError from error
        return skill

    async def _is_bound(self, *, skill_id: UUID) -> bool:
        counts = await self.session.execute(
            sa.select(
                sa.exists().where(AssistantSkillBindings.skill_id == skill_id),
                sa.exists().where(AppSkillBindings.skill_id == skill_id),
                sa.exists().where(GovernancePolicySkillBindings.skill_id == skill_id),
            )
        )
        return any(bool(value) for value in counts.one())

    async def _has_nonterminal_app_run(self, *, skill_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.exists().where(
                        AppRuns.job_id == Jobs.id,
                        Jobs.status.in_(
                            (Status.QUEUED.value, Status.IN_PROGRESS.value)
                        ),
                        AppRuns.skill_provenance.contains(
                            [{"skill_id": str(skill_id)}]
                        ),
                    )
                )
            )
        )

    @staticmethod
    def _resolved_query(
        binding_table: type[_BindingRow],
    ):
        is_organization = sa.and_(
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
        return (
            sa.select(
                binding_table,
                Skills,
                SkillRevisions,
                _CurrentSkillRevision.id.label("current_revision_id"),
                is_organization.label("is_organization"),
                sa.case(
                    (is_organization, _PublishedSkillRevision.id),
                    else_=_CurrentSkillRevision.id,
                ).label("attachable_revision_id"),
                sa.case(
                    (is_organization, Skills.published_revision_number),
                    else_=Skills.current_revision_number,
                ).label("attachable_revision_number"),
            )
            .join(Skills, Skills.id == binding_table.skill_id)
            .join(Spaces, Spaces.id == Skills.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == binding_table.skill_id,
                    SkillRevisions.id == binding_table.skill_revision_id,
                ),
            )
            .join(
                _CurrentSkillRevision,
                sa.and_(
                    _CurrentSkillRevision.skill_id == Skills.id,
                    _CurrentSkillRevision.revision_number
                    == Skills.current_revision_number,
                ),
            )
            .outerjoin(
                _PublishedSkillRevision,
                sa.and_(
                    _PublishedSkillRevision.skill_id == Skills.id,
                    _PublishedSkillRevision.revision_number
                    == Skills.published_revision_number,
                ),
            )
        )

    @staticmethod
    def _to_resolved(
        skill: Skills,
        revision: SkillRevisions,
        current_revision_id: UUID,
        is_organization: bool,
        attachable_revision_id: UUID | None,
        attachable_revision_number: int | None,
        position: int,
    ) -> ResolvedSkillBinding:
        return ResolvedSkillBinding(
            skill_id=skill.id,
            skill_revision_id=revision.id,
            current_revision_id=current_revision_id,
            skill_space_id=skill.space_id,
            slug=skill.slug,
            revision_number=revision.revision_number,
            current_revision_number=skill.current_revision_number,
            display_name=revision.display_name,
            instructions=revision.instructions,
            content_digest=revision.content_digest,
            position=position,
            source=(
                SkillBindingSource.ORGANIZATION
                if is_organization
                else SkillBindingSource.SPACE
            ),
            description=revision.description,
            is_active=skill.is_active,
            attachable_revision_id=attachable_revision_id,
            attachable_revision_number=attachable_revision_number,
        )

    async def _resolve_references(
        self,
        *,
        source_scope: ColumnElement[bool],
        references: list[SkillBindingReference],
        lock_active_state: bool,
    ) -> list[ResolvedSkillBinding]:
        if not references:
            return []
        skill_ids = [reference.skill_id for reference in references]
        revision_ids = [reference.skill_revision_id for reference in references]
        is_organization = sa.and_(
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
        statement = (
            sa.select(
                Skills,
                SkillRevisions,
                _CurrentSkillRevision.id.label("current_revision_id"),
                is_organization.label("is_organization"),
                sa.case(
                    (is_organization, _PublishedSkillRevision.id),
                    else_=_CurrentSkillRevision.id,
                ).label("attachable_revision_id"),
                sa.case(
                    (is_organization, Skills.published_revision_number),
                    else_=Skills.current_revision_number,
                ).label("attachable_revision_number"),
            )
            .join(SkillRevisions, SkillRevisions.skill_id == Skills.id)
            .join(
                _CurrentSkillRevision,
                sa.and_(
                    _CurrentSkillRevision.skill_id == Skills.id,
                    _CurrentSkillRevision.revision_number
                    == Skills.current_revision_number,
                ),
            )
            .join(Spaces, Spaces.id == Skills.space_id)
            .outerjoin(
                _PublishedSkillRevision,
                sa.and_(
                    _PublishedSkillRevision.skill_id == Skills.id,
                    _PublishedSkillRevision.revision_number
                    == Skills.published_revision_number,
                ),
            )
            .where(
                source_scope,
                Skills.id.in_(skill_ids),
                SkillRevisions.id.in_(revision_ids),
            )
        )
        if lock_active_state:
            statement = statement.with_for_update(read=True, of=Skills)
        rows = await self.session.execute(statement)
        by_reference = {
            SkillBindingReference(
                skill_id=skill.id,
                skill_revision_id=revision.id,
            ): (
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            )
            for (
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            ) in rows.all()
        }
        return [
            self._to_resolved(*by_reference[reference], position)
            for position, reference in enumerate(references)
            if reference in by_reference
        ]

    @classmethod
    def _resource_source_scope(
        cls,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
    ) -> ColumnElement[bool]:
        return sa.or_(
            sa.and_(
                Skills.space_id == parent_space_id,
                Spaces.tenant_id == tenant_id,
            ),
            sa.and_(*cls._organization_scope(tenant_id)),
        )

    async def resolve_references_for_execution_snapshot(
        self,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        return await self._resolve_references(
            source_scope=self._resource_source_scope(
                tenant_id=tenant_id,
                parent_space_id=parent_space_id,
            ),
            references=references,
            lock_active_state=False,
        )

    async def resolve_bound_references_for_binding_update(
        self,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        return await self._resolve_references(
            source_scope=self._resource_source_scope(
                tenant_id=tenant_id,
                parent_space_id=parent_space_id,
            ),
            references=references,
            lock_active_state=True,
        )

    async def resolve_local_references_for_binding_update(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        return await self._resolve_references(
            source_scope=Skills.space_id == space_id,
            references=references,
            lock_active_state=True,
        )

    async def resolve_published_references_for_binding_update(
        self,
        *,
        tenant_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        if not references:
            return []
        skill_ids = [reference.skill_id for reference in references]
        revision_ids = [reference.skill_revision_id for reference in references]
        rows = await self.session.execute(
            sa.select(
                Skills,
                SkillRevisions,
                _CurrentSkillRevision.id.label("current_revision_id"),
            )
            .join(Spaces, Spaces.id == Skills.space_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == Skills.id,
                    SkillRevisions.revision_number == Skills.published_revision_number,
                ),
            )
            .join(
                _CurrentSkillRevision,
                sa.and_(
                    _CurrentSkillRevision.skill_id == Skills.id,
                    _CurrentSkillRevision.revision_number
                    == Skills.current_revision_number,
                ),
            )
            .where(
                *self._organization_scope(tenant_id),
                Skills.id.in_(skill_ids),
                Skills.is_active.is_(True),
                SkillRevisions.id.in_(revision_ids),
            )
            .with_for_update(read=True, of=Skills)
        )
        by_reference = {
            SkillBindingReference(
                skill_id=skill.id,
                skill_revision_id=revision.id,
            ): (skill, revision, current_revision_id)
            for skill, revision, current_revision_id in rows.all()
        }
        return [
            self._to_resolved(
                *by_reference[reference],
                True,
                by_reference[reference][1].id,
                by_reference[reference][1].revision_number,
                position,
            )
            for position, reference in enumerate(references)
            if reference in by_reference
        ]

    async def lock_assistant_space_for_update(
        self, *, assistant_id: UUID
    ) -> UUID | None:
        return await self.session.scalar(
            sa.select(Assistants.space_id)
            .where(Assistants.id == assistant_id)
            .with_for_update()
        )

    async def lock_app_for_binding_update(self, *, app_id: UUID) -> bool:
        parent_id = await self.session.scalar(
            sa.select(Apps.id).where(Apps.id == app_id).with_for_update()
        )
        return parent_id is not None

    async def list_assistant_bindings(
        self, *, assistant_id: UUID
    ) -> list[ResolvedSkillBinding]:
        rows = await self.session.execute(
            self._resolved_query(AssistantSkillBindings)
            .where(AssistantSkillBindings.assistant_id == assistant_id)
            .order_by(AssistantSkillBindings.position)
        )
        return [
            self._to_resolved(
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
                binding.position,
            )
            for (
                binding,
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            ) in rows.all()
        ]

    async def has_assistant_bindings(self, *, assistant_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.exists().where(
                        AssistantSkillBindings.assistant_id == assistant_id
                    )
                )
            )
        )

    async def replace_assistant_bindings(
        self,
        *,
        assistant_id: UUID,
        tenant_id: UUID,
        space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None:
        await self.session.execute(
            sa.delete(AssistantSkillBindings).where(
                AssistantSkillBindings.assistant_id == assistant_id
            )
        )
        if bindings:
            await self.session.execute(
                sa.insert(AssistantSkillBindings),
                [
                    {
                        "assistant_id": assistant_id,
                        "tenant_id": tenant_id,
                        "space_id": space_id,
                        "skill_space_id": binding.skill_space_id,
                        "skill_id": binding.skill_id,
                        "skill_revision_id": binding.skill_revision_id,
                        "position": position,
                    }
                    for position, binding in enumerate(bindings)
                ],
            )

    async def list_app_bindings(self, *, app_id: UUID) -> list[ResolvedSkillBinding]:
        rows = await self.session.execute(
            self._resolved_query(AppSkillBindings)
            .where(AppSkillBindings.app_id == app_id)
            .order_by(AppSkillBindings.position)
        )
        return [
            self._to_resolved(
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
                binding.position,
            )
            for (
                binding,
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            ) in rows.all()
        ]

    async def list_app_bindings_for_execution_plan(
        self, *, app_id: UUID
    ) -> list[ResolvedSkillBinding]:
        rows = await self.session.execute(
            self._resolved_query(AppSkillBindings)
            .where(AppSkillBindings.app_id == app_id)
            .order_by(AppSkillBindings.position)
            .with_for_update(read=True, of=Skills)
        )
        return [
            self._to_resolved(
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
                binding.position,
            )
            for (
                binding,
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            ) in rows.all()
        ]

    async def replace_app_bindings(
        self,
        *,
        app_id: UUID,
        tenant_id: UUID,
        space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None:
        await self.session.execute(
            sa.delete(AppSkillBindings).where(AppSkillBindings.app_id == app_id)
        )
        if bindings:
            await self.session.execute(
                sa.insert(AppSkillBindings),
                [
                    {
                        "app_id": app_id,
                        "tenant_id": tenant_id,
                        "space_id": space_id,
                        "skill_space_id": binding.skill_space_id,
                        "skill_id": binding.skill_id,
                        "skill_revision_id": binding.skill_revision_id,
                        "position": position,
                    }
                    for position, binding in enumerate(bindings)
                ],
            )

    async def list_policy_bindings(
        self, *, policy_id: UUID
    ) -> list[ResolvedSkillBinding]:
        rows = await self.session.execute(
            self._resolved_query(GovernancePolicySkillBindings)
            .where(GovernancePolicySkillBindings.policy_id == policy_id)
            .order_by(GovernancePolicySkillBindings.position)
        )
        return [
            self._to_resolved(
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
                binding.position,
            )
            for (
                binding,
                skill,
                revision,
                current_revision_id,
                is_organization,
                attachable_revision_id,
                attachable_revision_number,
            ) in rows.all()
        ]

    async def replace_policy_bindings(
        self,
        *,
        policy_id: UUID,
        tenant_id: UUID,
        skill_space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None:
        await self.session.execute(
            sa.delete(GovernancePolicySkillBindings).where(
                GovernancePolicySkillBindings.policy_id == policy_id
            )
        )
        if bindings:
            await self.session.execute(
                sa.insert(GovernancePolicySkillBindings),
                [
                    {
                        "policy_id": policy_id,
                        "tenant_id": tenant_id,
                        "skill_space_id": skill_space_id,
                        "skill_id": binding.skill_id,
                        "skill_revision_id": binding.skill_revision_id,
                        "position": position,
                    }
                    for position, binding in enumerate(bindings)
                ],
            )
