from typing import TypeVar
from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.skill_table import (
    AppSkillBindings,
    AssistantSkillBindings,
    GovernancePolicySkillBindings,
    SkillRevisions,
    Skills,
)
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillBindingReference,
    SkillHasBindingsError,
    SkillRevision,
    SkillRevisionChange,
    SkillStatusChange,
)

_BindingRow = TypeVar(
    "_BindingRow",
    AssistantSkillBindings,
    AppSkillBindings,
    GovernancePolicySkillBindings,
)


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
    ) -> Skill:
        skill_id = uuid4()
        revision_id = uuid4()
        await self.session.execute(
            sa.insert(Skills).values(
                id=skill_id,
                space_id=space_id,
                slug=slug,
                is_active=True,
                current_revision_number=1,
                created_by_user_id=created_by_user_id,
            )
        )
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

    async def list_for_space(self, *, space_id: UUID) -> list[Skill]:
        result = await self.session.execute(
            self._skill_query()
            .where(Skills.space_id == space_id)
            .order_by(SkillRevisions.display_name, Skills.slug)
        )
        return [self._to_skill(row[0], row[1]) for row in result.all()]

    async def list_revisions(self, *, skill_id: UUID) -> list[SkillRevision]:
        rows = await self.session.scalars(
            sa.select(SkillRevisions)
            .where(SkillRevisions.skill_id == skill_id)
            .order_by(SkillRevisions.revision_number.desc())
        )
        return [self._to_revision(row) for row in rows.all()]

    async def create_revision(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
        content_digest: str,
        created_by_user_id: UUID,
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
        previous_revision_number = current_row.revision_number
        if (
            current_row.display_name == display_name
            and current_row.description == description
            and current_row.instructions == instructions
            and current_row.content_digest == content_digest
        ):
            return SkillRevisionChange(
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
        row = await self.session.scalar(
            sa.select(SkillRevisions).where(SkillRevisions.id == revision_id)
        )
        if row is None:
            raise RuntimeError("New Skill revision was not persisted")
        return SkillRevisionChange(
            revision=self._to_revision(row),
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
        previous_is_active = skill_row.is_active
        changed = previous_is_active != is_active
        if changed:
            await self.session.execute(
                sa.update(Skills)
                .where(Skills.id == skill_id)
                .values(is_active=is_active, updated_at=sa.func.now())
            )
        skill = await self.get(skill_id=skill_id)
        if skill is None:
            raise RuntimeError("Locked Skill disappeared during status update")
        return SkillStatusChange(
            skill=skill,
            changed=changed,
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
        if await self._is_bound(skill_id=skill_id):
            raise SkillHasBindingsError
        await self.session.execute(sa.delete(Skills).where(Skills.id == skill_id))
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

    @staticmethod
    def _resolved_query(
        binding_table: type[_BindingRow],
    ) -> sa.Select[tuple[_BindingRow, Skills, SkillRevisions]]:
        return (
            sa.select(binding_table, Skills, SkillRevisions)
            .join(Skills, Skills.id == binding_table.skill_id)
            .join(
                SkillRevisions,
                sa.and_(
                    SkillRevisions.skill_id == binding_table.skill_id,
                    SkillRevisions.id == binding_table.skill_revision_id,
                ),
            )
        )

    @staticmethod
    def _to_resolved(
        skill: Skills, revision: SkillRevisions, position: int
    ) -> ResolvedSkillBinding:
        return ResolvedSkillBinding(
            skill_id=skill.id,
            skill_revision_id=revision.id,
            slug=skill.slug,
            revision_number=revision.revision_number,
            display_name=revision.display_name,
            instructions=revision.instructions,
            content_digest=revision.content_digest,
            position=position,
            description=revision.description,
            is_active=skill.is_active,
        )

    async def _resolve_references(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
        lock_active_state: bool,
    ) -> list[ResolvedSkillBinding]:
        if not references:
            return []
        skill_ids = [reference.skill_id for reference in references]
        revision_ids = [reference.skill_revision_id for reference in references]
        statement = (
            sa.select(Skills, SkillRevisions)
            .join(SkillRevisions, SkillRevisions.skill_id == Skills.id)
            .where(
                Skills.space_id == space_id,
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
            ): (skill, revision)
            for skill, revision in rows.all()
        }
        return [
            self._to_resolved(*by_reference[reference], position)
            for position, reference in enumerate(references)
            if reference in by_reference
        ]

    async def resolve_references(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        return await self._resolve_references(
            space_id=space_id,
            references=references,
            lock_active_state=False,
        )

    async def resolve_references_for_binding_update(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        return await self._resolve_references(
            space_id=space_id,
            references=references,
            lock_active_state=True,
        )

    async def lock_assistant_for_binding_update(self, *, assistant_id: UUID) -> bool:
        parent_id = await self.session.scalar(
            sa.select(Assistants.id)
            .where(Assistants.id == assistant_id)
            .with_for_update()
        )
        return parent_id is not None

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
            self._to_resolved(skill, revision, binding.position)
            for binding, skill, revision in rows.all()
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
                        "space_id": space_id,
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
            self._to_resolved(skill, revision, binding.position)
            for binding, skill, revision in rows.all()
        ]

    async def replace_app_bindings(
        self,
        *,
        app_id: UUID,
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
                        "space_id": space_id,
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
            self._to_resolved(skill, revision, binding.position)
            for binding, skill, revision in rows.all()
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
