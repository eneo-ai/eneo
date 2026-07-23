from typing import Protocol
from uuid import UUID

from eneo.skills.domain.skill import (
    PublishedSkill,
    PublishedSkillSummary,
    ResolvedSkillBinding,
    Skill,
    SkillAdoptionCursor,
    SkillAdoptionProjectionPage,
    SkillBindingReference,
    SkillCatalogEntry,
    SkillExecutionBlock,
    SkillExecutionBlockChange,
    SkillPublicationChange,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionSummary,
    SkillStatusChange,
    SkillSummary,
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
        is_active: bool = True,
    ) -> Skill: ...

    async def get(self, *, skill_id: UUID) -> Skill | None: ...

    async def list_catalog_entries(
        self,
        *,
        space_id: UUID,
        limit: int,
        after_slug: str | None,
        query: str | None,
    ) -> list[SkillCatalogEntry]: ...

    async def count_catalog_entries(
        self,
        *,
        space_id: UUID,
        query: str | None,
    ) -> int: ...

    async def list_organization_for_tenant(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after_slug: str | None,
        search: str | None = None,
    ) -> list[SkillSummary]: ...

    async def get_organization_for_tenant(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> Skill | None: ...

    async def get_organization_adoption_projection_page(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        limit: int,
        after: SkillAdoptionCursor | None,
    ) -> SkillAdoptionProjectionPage | None: ...

    async def list_published_for_tenant(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after_slug: str | None,
        search: str | None = None,
    ) -> list[PublishedSkillSummary]: ...

    async def get_published_for_tenant(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> PublishedSkill | None: ...

    async def get_revision(
        self, *, skill_id: UUID, revision_id: UUID
    ) -> SkillRevision | None: ...

    async def list_revision_summaries(
        self,
        *,
        skill_id: UUID,
        limit: int,
        before_revision_number: int | None,
    ) -> list[SkillRevisionSummary]: ...

    async def count_revisions(self, *, skill_id: UUID) -> int: ...

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
    ) -> SkillRevisionChange | None: ...

    async def set_active(
        self, *, skill_id: UUID, is_active: bool
    ) -> SkillStatusChange | None: ...

    async def publish_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        expected_revision_id: UUID,
    ) -> SkillPublicationChange | None: ...

    async def unpublish_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> SkillPublicationChange | None: ...

    async def delete(self, *, skill_id: UUID) -> Skill | None: ...

    async def delete_organization(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> Skill | None: ...

    async def get_active_execution_block(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
    ) -> SkillExecutionBlock | None: ...

    async def list_active_execution_blocks(
        self,
        *,
        tenant_id: UUID,
        skill_ids: list[UUID],
    ) -> dict[UUID, SkillExecutionBlock]: ...

    async def block_organization_skill(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        blocked_by_user_id: UUID,
        reason: str,
    ) -> SkillExecutionBlockChange | None: ...

    async def unblock_organization_skill(
        self,
        *,
        tenant_id: UUID,
        skill_id: UUID,
        expected_block_id: UUID,
        unblocked_by_user_id: UUID,
        reason: str,
    ) -> SkillExecutionBlockChange | None: ...

    async def resolve_references_for_execution_snapshot(
        self,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def resolve_bound_references_for_binding_update(
        self,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def resolve_local_references_for_binding_update(
        self,
        *,
        space_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def resolve_published_references_for_binding_update(
        self,
        *,
        tenant_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]: ...

    async def lock_assistant_space_for_update(
        self, *, assistant_id: UUID
    ) -> UUID | None: ...

    async def lock_app_for_binding_update(self, *, app_id: UUID) -> bool: ...

    async def list_assistant_bindings(
        self, *, assistant_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def has_assistant_bindings(self, *, assistant_id: UUID) -> bool: ...

    async def replace_assistant_bindings(
        self,
        *,
        assistant_id: UUID,
        tenant_id: UUID,
        space_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None: ...

    async def list_app_bindings(
        self, *, app_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def list_app_bindings_for_execution_plan(
        self, *, app_id: UUID
    ) -> list[ResolvedSkillBinding]: ...

    async def replace_app_bindings(
        self,
        *,
        app_id: UUID,
        tenant_id: UUID,
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
