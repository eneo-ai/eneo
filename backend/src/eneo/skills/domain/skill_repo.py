from typing import Protocol
from uuid import UUID

from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillBindingReference,
    SkillRevision,
    SkillRevisionChange,
    SkillStatusChange,
)


class SkillRepo(Protocol):
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
    ) -> Skill: ...

    async def get(self, *, skill_id: UUID) -> Skill | None: ...

    async def list_for_space(self, *, space_id: UUID) -> list[Skill]: ...

    async def list_revisions(self, *, skill_id: UUID) -> list[SkillRevision]: ...

    async def create_revision(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
        content_digest: str,
        created_by_user_id: UUID,
    ) -> SkillRevisionChange | None: ...

    async def set_active(
        self, *, skill_id: UUID, is_active: bool
    ) -> SkillStatusChange | None: ...

    async def delete(self, *, skill_id: UUID) -> Skill | None: ...

    async def resolve_references(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def resolve_references_for_binding_update(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def lock_assistant_for_binding_update(
        self, *, assistant_id: UUID
    ) -> bool: ...

    async def lock_app_for_binding_update(self, *, app_id: UUID) -> bool: ...

    async def list_assistant_bindings(
        self, *, assistant_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def has_assistant_bindings(self, *, assistant_id: UUID) -> bool: ...

    async def replace_assistant_bindings(
        self,
        *,
        assistant_id: UUID,
        space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None: ...

    async def list_app_bindings(
        self, *, app_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def replace_app_bindings(
        self,
        *,
        app_id: UUID,
        space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None: ...

    async def list_policy_bindings(
        self, *, policy_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def replace_policy_bindings(
        self,
        *,
        policy_id: UUID,
        tenant_id: UUID,
        skill_space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None: ...
