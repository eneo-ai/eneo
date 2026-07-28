from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    SkillRevisionConflictException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission, validate_permission
from eneo.skills.domain.skill import (
    MAX_SKILL_CATALOG_PAGE_LIMIT,
    MAX_SKILL_CATALOG_QUERY_LENGTH,
    AssistantSkillBindingReplacement,
    NormalizedSkillContent,
    PersonalChatPinOverride,
    PublishedSkillDeactivationError,
    ResolvedSkillBinding,
    Skill,
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingProjection,
    SkillBindingReference,
    SkillCatalogPage,
    SkillComposition,
    SkillExecutionBlock,
    SkillExecutionBlockedException,
    SkillExecutionReference,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionConflictError,
    SkillRevisionPage,
    SkillRevisionRestore,
    SkillRuntimeResolution,
    SkillStatusChange,
    SkillTurnPlan,
    compose_skill_instructions,
    parse_skill_revision_cursor,
    validate_skill_slug,
)
from eneo.skills.domain.skill_repo import SkillRepo
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService


class SkillService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: SkillRepo,
        space_service: "SpaceService",
        actor_manager: "ActorManager",
    ) -> None:
        self.user = user
        self.repo = repo
        self.space_service = space_service
        self.actor_manager = actor_manager

    async def _space(self, space_id: UUID) -> "Space":
        return await self.space_service.get_space(space_id)

    @staticmethod
    def _tenant_id(space: "Space") -> UUID:
        if space.tenant_id is None:
            raise RuntimeError("Persisted Space is missing its tenant")
        return space.tenant_id

    @staticmethod
    def _require_space_skill_mutation(space: "Space") -> None:
        if space.is_organization():
            raise BadRequestException(
                "Organisation Skills must be managed through the organisation "
                "Skill workflow"
            )

    async def list_skills(
        self,
        *,
        space_id: UUID,
        limit: int,
        cursor: str | None,
        query: str | None,
    ) -> SkillCatalogPage:
        space = await self._space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to read Skills in this Space"
            )
        if not 1 <= limit <= MAX_SKILL_CATALOG_PAGE_LIMIT:
            raise BadRequestException(
                "Skill catalog limit must be between 1 and "
                f"{MAX_SKILL_CATALOG_PAGE_LIMIT}"
            )

        after_slug = None
        if cursor is not None:
            try:
                after_slug = validate_skill_slug(cursor)
            except BadRequestException as error:
                raise BadRequestException("Invalid Skill catalog cursor") from error
            if after_slug != cursor:
                raise BadRequestException("Invalid Skill catalog cursor")

        normalized_query = query.strip() if query is not None else None
        normalized_query = normalized_query or None
        if (
            normalized_query is not None
            and len(normalized_query) > MAX_SKILL_CATALOG_QUERY_LENGTH
        ):
            raise BadRequestException(
                "Skill catalog query cannot exceed "
                f"{MAX_SKILL_CATALOG_QUERY_LENGTH} characters"
            )

        entries = await self.repo.list_catalog_entries(
            space_id=space_id,
            limit=limit + 1,
            after_slug=after_slug,
            query=normalized_query,
        )
        visible = entries[:limit]
        next_cursor = visible[-1].slug if len(entries) > limit and visible else None
        return SkillCatalogPage(
            items=tuple(visible),
            limit=limit,
            next_cursor=next_cursor,
            total_count=await self.repo.count_catalog_entries(
                space_id=space_id,
                query=normalized_query,
            ),
        )

    async def get_skill(self, *, skill_id: UUID) -> Skill:
        skill = await self.repo.get(skill_id=skill_id)
        if skill is None:
            raise NotFoundException()
        space = await self._space(skill.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_skills():
            raise UnauthorizedException("You do not have permission to read this Skill")
        return skill

    async def create_skill(
        self,
        *,
        space_id: UUID,
        slug: str,
        display_name: str,
        description: str,
        instructions: str,
    ) -> Skill:
        space = await self._space(space_id)
        self._require_space_skill_mutation(space)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_create_skills():
            raise UnauthorizedException(
                "You do not have permission to create Skills in this Space"
            )
        return await self._create_skill_record(
            space_id=space_id,
            slug=slug,
            display_name=display_name,
            description=description,
            instructions=instructions,
        )

    async def _create_skill_record(
        self,
        *,
        space_id: UUID,
        slug: str,
        display_name: str,
        description: str,
        instructions: str,
    ) -> Skill:
        normalized_slug = validate_skill_slug(slug)
        content = NormalizedSkillContent.create(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        return await self.repo.create(
            space_id=space_id,
            slug=normalized_slug,
            display_name=content.display_name,
            description=content.description,
            instructions=content.instructions,
            content_digest=content.content_digest,
            created_by_user_id=self.user.id,
        )

    async def create_revision(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
    ) -> SkillRevisionChange:
        skill = await self.get_skill(skill_id=skill_id)
        space = await self._space(skill.space_id)
        self._require_space_skill_mutation(space)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to revise this Skill"
            )
        return await self._create_revision_record(
            skill_id=skill.id,
            display_name=display_name,
            description=description,
            instructions=instructions,
        )

    async def _create_revision_record(
        self,
        *,
        skill_id: UUID,
        display_name: str,
        description: str,
        instructions: str,
    ) -> SkillRevisionChange:
        content = NormalizedSkillContent.create(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        change = await self.repo.create_revision(
            skill_id=skill_id,
            display_name=content.display_name,
            description=content.description,
            instructions=content.instructions,
            content_digest=content.content_digest,
            created_by_user_id=self.user.id,
        )
        if change is None:
            raise NotFoundException()
        return change

    async def list_revision_summaries(
        self,
        *,
        space_id: UUID,
        skill_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> SkillRevisionPage:
        skill = await self.get_skill(skill_id=skill_id)
        if skill.space_id != space_id:
            raise NotFoundException()
        before_revision_number = parse_skill_revision_cursor(cursor)
        revisions = await self.repo.list_revision_summaries(
            skill_id=skill.id,
            limit=limit + 1,
            before_revision_number=before_revision_number,
        )
        visible = revisions[:limit]
        next_cursor = (
            visible[-1].revision_number if len(revisions) > limit and visible else None
        )
        return SkillRevisionPage(
            items=tuple(visible),
            limit=limit,
            next_cursor=next_cursor,
            total_count=await self.repo.count_revisions(skill_id=skill.id),
        )

    async def get_revision(
        self,
        *,
        space_id: UUID,
        skill_id: UUID,
        revision_id: UUID,
    ) -> SkillRevision:
        skill = await self.get_skill(skill_id=skill_id)
        if skill.space_id != space_id:
            raise NotFoundException()
        revision = await self.repo.get_revision(
            skill_id=skill.id,
            revision_id=revision_id,
        )
        if revision is None:
            raise NotFoundException()
        return revision

    async def restore_revision(
        self,
        *,
        space_id: UUID,
        skill_id: UUID,
        source_revision_id: UUID,
        reviewed_current_revision_id: UUID,
    ) -> SkillRevisionRestore:
        skill = await self.get_skill(skill_id=skill_id)
        if skill.space_id != space_id:
            raise NotFoundException()
        space = await self._space(skill.space_id)
        self._require_space_skill_mutation(space)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to restore this Skill"
            )
        source_revision = await self.repo.get_revision(
            skill_id=skill.id,
            revision_id=source_revision_id,
        )
        if source_revision is None:
            raise NotFoundException()
        try:
            change = await self.repo.create_revision(
                skill_id=skill.id,
                display_name=source_revision.display_name,
                description=source_revision.description,
                instructions=source_revision.instructions,
                content_digest=source_revision.content_digest,
                created_by_user_id=self.user.id,
                expected_current_revision_id=reviewed_current_revision_id,
            )
        except SkillRevisionConflictError as error:
            raise SkillRevisionConflictException(
                "This Skill changed after you reviewed it. Compare the latest "
                "revision before restoring again."
            ) from error
        if change is None:
            raise NotFoundException()
        return SkillRevisionRestore(
            source_revision=source_revision,
            change=change,
        )

    async def set_active(self, *, skill_id: UUID, is_active: bool) -> SkillStatusChange:
        skill = await self.get_skill(skill_id=skill_id)
        space = await self._space(skill.space_id)
        if space.is_organization():
            raise BadRequestException(
                "Organisation Skill availability is controlled by publication"
            )
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to change this Skill"
            )
        try:
            change = await self.repo.set_active(skill_id=skill.id, is_active=is_active)
        except PublishedSkillDeactivationError as error:
            raise BadRequestException(
                "Unpublish this Skill before deactivating it."
            ) from error
        if change is None:
            raise NotFoundException()
        return change

    async def delete_skill(self, *, skill_id: UUID) -> Skill:
        skill = await self.get_skill(skill_id=skill_id)
        space = await self._space(skill.space_id)
        self._require_space_skill_mutation(space)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_delete_skills():
            raise UnauthorizedException(
                "You do not have permission to delete this Skill"
            )
        deleted = await self.repo.delete(skill_id=skill.id)
        if deleted is None:
            raise NotFoundException()
        return deleted

    async def _validate_reference_count(
        self,
        *,
        tenant_id: UUID,
        references: list[SkillBindingReference],
    ) -> None:
        # The stored organisation policy is the source of truth for the
        # attachment guard; the SKILL_MAX_BINDINGS environment value only
        # seeded it during migration. The shared lock serializes this write
        # against a concurrent admin policy change so the guard never
        # validates against a superseded limit.
        policy = await self.repo.get_or_seed_runtime_policy(
            tenant_id=tenant_id, shared_lock=True
        )
        if len(references) > policy.max_attached_skills:
            raise BadRequestException(
                f"A resource cannot use more than {policy.max_attached_skills} Skills"
            )
        if len({reference.skill_id for reference in references}) != len(references):
            raise BadRequestException("A Skill can only be attached once")
        if len(set(references)) != len(references):
            raise BadRequestException("Duplicate Skill revision binding")

    @staticmethod
    def _binding_reference(binding: ResolvedSkillBinding) -> SkillBindingReference:
        return SkillBindingReference(
            skill_id=binding.skill_id,
            skill_revision_id=binding.skill_revision_id,
        )

    async def _resolve_retained_references(
        self,
        *,
        tenant_id: UUID,
        parent_space_id: UUID,
        references: list[SkillBindingReference],
        existing: list[ResolvedSkillBinding],
    ) -> tuple[
        dict[SkillBindingReference, ResolvedSkillBinding], list[SkillBindingReference]
    ]:
        existing_references = {self._binding_reference(binding) for binding in existing}
        retained_references = [
            reference for reference in references if reference in existing_references
        ]
        retained = (
            await self.repo.resolve_bound_references_for_binding_update(
                tenant_id=tenant_id,
                parent_space_id=parent_space_id,
                references=retained_references,
            )
            if retained_references
            else []
        )
        if len(retained) != len(retained_references):
            raise BadRequestException(
                "One or more existing Skill bindings are no longer available"
            )
        return (
            {self._binding_reference(binding): binding for binding in retained},
            [
                reference
                for reference in references
                if reference not in existing_references
            ],
        )

    async def _reject_blocked_references(
        self,
        *,
        tenant_id: UUID,
        references: list[SkillBindingReference],
    ) -> None:
        if not references:
            return
        blocks = await self.repo.list_active_execution_blocks(
            tenant_id=tenant_id,
            skill_ids=[reference.skill_id for reference in references],
        )
        if blocks:
            raise BadRequestException(
                "Blocked organisation Skills cannot receive new or changed bindings"
            )

    @classmethod
    def _order_resolved_bindings(
        cls,
        *,
        references: list[SkillBindingReference],
        resolved_groups: tuple[list[ResolvedSkillBinding], ...],
        existing: list[ResolvedSkillBinding],
        requested_modes: dict[UUID, SkillActivationMode] | None = None,
        missing_error: Exception,
    ) -> list[ResolvedSkillBinding]:
        resolved_by_reference = {
            cls._binding_reference(binding): binding
            for group in resolved_groups
            for binding in group
        }
        if any(reference not in resolved_by_reference for reference in references):
            raise missing_error
        # Explicit mode intent wins; otherwise a retained Skill keeps its mode.
        existing_mode_by_skill_id = {
            binding.skill_id: binding.activation_mode for binding in existing
        }
        requested_modes = requested_modes or {}
        return [
            replace(
                resolved_by_reference[reference],
                position=position,
                activation_mode=requested_modes.get(
                    reference.skill_id,
                    existing_mode_by_skill_id.get(
                        reference.skill_id,
                        resolved_by_reference[reference].activation_mode,
                    ),
                ),
            )
            for position, reference in enumerate(references)
        ]

    @classmethod
    def _mode_changed_retained_references(
        cls,
        *,
        retained_by_reference: dict[SkillBindingReference, ResolvedSkillBinding],
        existing: list[ResolvedSkillBinding],
        requested_modes: dict[UUID, SkillActivationMode],
    ) -> list[SkillBindingReference]:
        existing_by_reference = {
            cls._binding_reference(binding): binding for binding in existing
        }
        return [
            reference
            for reference in retained_by_reference
            if reference.skill_id in requested_modes
            and requested_modes[reference.skill_id]
            is not existing_by_reference[reference].activation_mode
        ]

    async def _resolve_resource_references(
        self,
        *,
        space_id: UUID,
        tenant_id: UUID,
        organization_space: bool,
        references: list[SkillBindingReference],
        existing: list[ResolvedSkillBinding],
        requested_modes: dict[UUID, SkillActivationMode] | None = None,
    ) -> list[ResolvedSkillBinding]:
        await self._validate_reference_count(tenant_id=tenant_id, references=references)
        retained_by_reference, new_references = await self._resolve_retained_references(
            tenant_id=tenant_id,
            parent_space_id=space_id,
            references=references,
            existing=existing,
        )
        local = (
            []
            if organization_space or not new_references
            else await self.repo.resolve_local_references_for_binding_update(
                space_id=space_id,
                references=new_references,
            )
        )
        if any(not binding.is_active for binding in local):
            raise BadRequestException("Inactive Skills cannot receive new bindings")
        local_references = {self._binding_reference(binding) for binding in local}
        catalogue_references = [
            reference
            for reference in new_references
            if reference not in local_references
        ]
        published = (
            await self.repo.resolve_published_references_for_binding_update(
                tenant_id=tenant_id,
                references=catalogue_references,
            )
            if catalogue_references
            else []
        )
        # Resolution holds the Skill rows FOR SHARE, so this read observes a
        # concurrent execution block that acquired FOR UPDATE first.
        requested_modes = requested_modes or {}
        mode_changed_retained_references = self._mode_changed_retained_references(
            retained_by_reference=retained_by_reference,
            existing=existing,
            requested_modes=requested_modes,
        )
        await self._reject_blocked_references(
            tenant_id=tenant_id,
            references=[*new_references, *mode_changed_retained_references],
        )
        return self._order_resolved_bindings(
            references=references,
            resolved_groups=(
                list(retained_by_reference.values()),
                local,
                published,
            ),
            existing=existing,
            requested_modes=requested_modes,
            missing_error=NotFoundException(
                "One or more Skill revisions are unavailable for this resource"
            ),
        )

    async def _resolve_governance_references(
        self,
        *,
        organization_space_id: UUID,
        references: list[SkillBindingReference],
        existing: list[ResolvedSkillBinding],
        requested_modes: dict[UUID, SkillActivationMode] | None = None,
    ) -> list[ResolvedSkillBinding]:
        await self._validate_reference_count(
            tenant_id=self.user.tenant_id, references=references
        )
        retained_by_reference, new_references = await self._resolve_retained_references(
            tenant_id=self.user.tenant_id,
            parent_space_id=organization_space_id,
            references=references,
            existing=existing,
        )
        published = (
            await self.repo.resolve_published_references_for_binding_update(
                tenant_id=self.user.tenant_id,
                references=new_references,
            )
            if new_references
            else []
        )
        # Resolution holds the Skill rows FOR SHARE, so this read observes a
        # concurrent execution block that acquired FOR UPDATE first.
        requested_modes = requested_modes or {}
        mode_changed_retained_references = self._mode_changed_retained_references(
            retained_by_reference=retained_by_reference,
            existing=existing,
            requested_modes=requested_modes,
        )
        await self._reject_blocked_references(
            tenant_id=self.user.tenant_id,
            references=[*new_references, *mode_changed_retained_references],
        )
        return self._order_resolved_bindings(
            references=references,
            resolved_groups=(list(retained_by_reference.values()), published),
            existing=existing,
            requested_modes=requested_modes,
            missing_error=BadRequestException(
                "Personal Chat can only use published organisation Skill versions"
            ),
        )

    async def list_assistant_bindings(
        self, *, space_id: UUID, assistant_id: UUID
    ) -> list[ResolvedSkillBinding]:
        space = await self._space(space_id)
        assistant = space.get_assistant(assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_assistant(assistant=assistant):
            raise UnauthorizedException(
                "You do not have permission to read this Assistant"
            )
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to read Skills in this Space"
            )
        bindings = await self.repo.list_assistant_bindings(assistant_id=assistant_id)
        if space.is_personal() and assistant.is_default:
            if bindings:
                raise BadRequestException(
                    "Personal default Assistant has invalid direct Skill bindings"
                )
            return []
        return bindings

    async def list_assistant_binding_projections(
        self,
        *,
        space_id: UUID,
        assistant_id: UUID,
    ) -> list[SkillBindingProjection]:
        bindings = await self.list_assistant_bindings(
            space_id=space_id,
            assistant_id=assistant_id,
        )
        return await self._project_bindings(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )

    async def replace_assistant_bindings(
        self,
        *,
        space_id: UUID,
        assistant_id: UUID,
        intents: list[SkillBindingIntent],
    ) -> AssistantSkillBindingReplacement:
        if self.user.active_api_key is not None:
            raise UnauthorizedException("Skill binding changes require a session token")
        space = await self._space(space_id)
        assistant = space.get_assistant(assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit this Assistant"
            )
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to attach Skills in this Space"
            )
        if space.is_personal() and assistant.is_default:
            raise BadRequestException(
                "Personal default Assistant Skills are controlled by tenant governance"
            )
        locked_space_id = await self.repo.lock_assistant_space_for_update(
            assistant_id=assistant_id
        )
        if locked_space_id != space_id:
            raise NotFoundException()
        existing = await self.repo.list_assistant_bindings(assistant_id=assistant_id)
        references = [intent.reference for intent in intents]
        requested_modes = {
            intent.reference.skill_id: intent.activation_mode
            for intent in intents
            if intent.activation_mode is not None
        }
        existing_by_skill_id = {binding.skill_id: binding for binding in existing}
        tenant_id = self._tenant_id(space)
        resolved = await self._resolve_resource_references(
            space_id=space_id,
            tenant_id=tenant_id,
            organization_space=space.is_organization(),
            references=references,
            existing=existing,
            requested_modes=requested_modes,
        )
        on_demand_skill_ids_requiring_validation = frozenset(
            binding.skill_id
            for binding in resolved
            if binding.activation_mode is SkillActivationMode.ON_DEMAND
            and (
                (stored := existing_by_skill_id.get(binding.skill_id)) is None
                or stored.skill_revision_id != binding.skill_revision_id
                or stored.activation_mode is not SkillActivationMode.ON_DEMAND
            )
        )
        await self.repo.replace_assistant_bindings(
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            space_id=space_id,
            bindings=resolved,
        )
        return AssistantSkillBindingReplacement(
            bindings=tuple(resolved),
            on_demand_skill_ids_requiring_validation=(
                on_demand_skill_ids_requiring_validation
            ),
        )

    async def list_app_bindings(
        self, *, space_id: UUID, app_id: UUID
    ) -> list[ResolvedSkillBinding]:
        space = await self._space(space_id)
        app = space.get_app(app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_app(app=app):
            raise UnauthorizedException("You do not have permission to read this App")
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to read Skills in this Space"
            )
        return await self.repo.list_app_bindings(app_id=app_id)

    async def list_app_binding_projections(
        self,
        *,
        space_id: UUID,
        app_id: UUID,
    ) -> list[SkillBindingProjection]:
        bindings = await self.list_app_bindings(
            space_id=space_id,
            app_id=app_id,
        )
        return await self._project_bindings(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )

    async def replace_app_bindings(
        self,
        *,
        space_id: UUID,
        app_id: UUID,
        references: list[SkillBindingReference],
    ) -> list[ResolvedSkillBinding]:
        if self.user.active_api_key is not None:
            raise UnauthorizedException("Skill binding changes require a session token")
        space = await self._space(space_id)
        space.get_app(app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_apps():
            raise UnauthorizedException("You do not have permission to edit this App")
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to attach Skills in this Space"
            )
        if not await self.repo.lock_app_for_binding_update(app_id=app_id):
            raise NotFoundException()
        existing = await self.repo.list_app_bindings(app_id=app_id)
        tenant_id = self._tenant_id(space)
        resolved = await self._resolve_resource_references(
            space_id=space_id,
            tenant_id=tenant_id,
            organization_space=space.is_organization(),
            references=references,
            existing=existing,
        )
        await self.repo.replace_app_bindings(
            app_id=app_id,
            tenant_id=tenant_id,
            space_id=space_id,
            bindings=resolved,
        )
        return resolved

    async def replace_governance_bindings(
        self,
        *,
        policy_id: UUID,
        organization_space_id: UUID,
        intents: list[SkillBindingIntent],
    ) -> list[ResolvedSkillBinding]:
        if self.user.active_api_key is not None:
            raise UnauthorizedException("Skill policy changes require a session token")
        validate_permission(self.user, Permission.ADMIN)
        space = await self._space(organization_space_id)
        if not space.is_organization() or space.tenant_id != self.user.tenant_id:
            raise BadRequestException(
                "Governance Skills must belong to this tenant's organisation Space"
            )
        existing = await self.repo.list_policy_bindings(policy_id=policy_id)
        references = [intent.reference for intent in intents]
        requested_modes = {
            intent.reference.skill_id: intent.activation_mode
            for intent in intents
            if intent.activation_mode is not None
        }
        resolved = await self._resolve_governance_references(
            organization_space_id=organization_space_id,
            references=references,
            existing=existing,
            requested_modes=requested_modes,
        )
        await self.repo.replace_policy_bindings(
            policy_id=policy_id,
            tenant_id=self.user.tenant_id,
            skill_space_id=organization_space_id,
            bindings=resolved,
        )
        return resolved

    async def list_governance_bindings(
        self, *, policy_id: UUID
    ) -> list[ResolvedSkillBinding]:
        validate_permission(self.user, Permission.ADMIN)
        return await self.repo.list_policy_bindings(policy_id=policy_id)

    async def list_governance_binding_projections(
        self,
        *,
        policy_id: UUID,
    ) -> list[SkillBindingProjection]:
        bindings = await self.list_governance_bindings(policy_id=policy_id)
        return await self._project_bindings(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )

    async def _active_execution_blocks(
        self,
        *,
        tenant_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> dict[UUID, SkillExecutionBlock]:
        if not bindings:
            return {}
        return await self.repo.list_active_execution_blocks(
            tenant_id=tenant_id,
            skill_ids=[binding.skill_id for binding in bindings],
        )

    async def _project_bindings(
        self,
        *,
        tenant_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> list[SkillBindingProjection]:
        blocks = await self._active_execution_blocks(
            tenant_id=tenant_id,
            bindings=bindings,
        )
        return [
            SkillBindingProjection(
                binding=binding,
                execution_blocked=binding.skill_id in blocks,
            )
            for binding in bindings
        ]

    async def _resolve_execution_blocks(
        self,
        *,
        tenant_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> SkillRuntimeResolution:
        blocks = await self._active_execution_blocks(
            tenant_id=tenant_id,
            bindings=bindings,
        )
        return SkillRuntimeResolution(
            eligible=tuple(
                binding for binding in bindings if binding.skill_id not in blocks
            ),
            blocked=tuple(
                binding for binding in bindings if binding.skill_id in blocks
            ),
        )

    async def _require_execution_allowed(
        self,
        *,
        tenant_id: UUID,
        bindings: list[ResolvedSkillBinding],
    ) -> None:
        blocks = await self._active_execution_blocks(
            tenant_id=tenant_id,
            bindings=bindings,
        )
        for binding in sorted(bindings, key=lambda item: item.position):
            block = blocks.get(binding.skill_id)
            if block is not None:
                raise SkillExecutionBlockedException(
                    block=block,
                    binding=binding,
                )

    async def resolve_governance_bindings_for_runtime(
        self,
        *,
        policy_id: UUID,
        personal_chat_pin_override: PersonalChatPinOverride | None = None,
    ) -> SkillRuntimeResolution:
        bindings = await self.repo.list_policy_bindings(policy_id=policy_id)
        if personal_chat_pin_override is not None:
            overridden_binding = next(
                (
                    binding
                    for binding in bindings
                    if binding.skill_id == personal_chat_pin_override.skill_id
                ),
                None,
            )
            if overridden_binding is not None:
                candidate = await self.repo.resolve_references_for_execution_snapshot(
                    tenant_id=self.user.tenant_id,
                    parent_space_id=overridden_binding.skill_space_id,
                    references=[
                        SkillBindingReference(
                            skill_id=personal_chat_pin_override.skill_id,
                            skill_revision_id=personal_chat_pin_override.to_revision_id,
                        )
                    ],
                )
                if candidate:
                    candidate_binding = replace(
                        candidate[0],
                        position=overridden_binding.position,
                        activation_mode=overridden_binding.activation_mode,
                    )
                    bindings = [
                        candidate_binding
                        if binding.skill_id == personal_chat_pin_override.skill_id
                        else binding
                        for binding in bindings
                    ]
        return await self._resolve_execution_blocks(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )

    async def resolve_assistant_bindings_for_runtime(
        self,
        *,
        assistant_id: UUID,
    ) -> SkillRuntimeResolution:
        bindings = await self.repo.list_assistant_bindings(assistant_id=assistant_id)
        return await self._resolve_execution_blocks(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )

    async def create_turn_plan(
        self,
        *,
        base_instructions: str,
        resolution: SkillRuntimeResolution,
    ) -> SkillTurnPlan:
        policy = await self.repo.get_or_seed_runtime_policy(
            tenant_id=self.user.tenant_id
        )
        return SkillTurnPlan.create(
            base_instructions=base_instructions,
            resolution=resolution,
            policy=policy,
        )

    async def compose_for_app(
        self, *, app_id: UUID, base_instructions: str
    ) -> SkillComposition:
        bindings = await self.repo.list_app_bindings_for_execution_plan(app_id=app_id)
        await self._require_execution_allowed(
            tenant_id=self.user.tenant_id,
            bindings=bindings,
        )
        return compose_skill_instructions(
            base_instructions=base_instructions, bindings=bindings
        )

    async def compose_for_execution_snapshot(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        provenance: tuple[SkillExecutionReference, ...],
        base_instructions: str,
    ) -> SkillComposition:
        if not provenance:
            return compose_skill_instructions(
                base_instructions=base_instructions, bindings=[]
            )

        ordered = sorted(provenance, key=lambda reference: reference.position)
        positions = [reference.position for reference in ordered]
        if any(position < 0 for position in positions):
            raise BadRequestException("Skill binding positions cannot be negative")
        if len(set(positions)) != len(positions):
            raise BadRequestException("Skill binding positions must be unique")
        skill_ids = [reference.skill_id for reference in ordered]
        if len(set(skill_ids)) != len(skill_ids):
            raise BadRequestException("A Skill can only be bound once to a resource")

        references = [
            SkillBindingReference(
                skill_id=reference.skill_id,
                skill_revision_id=reference.skill_revision_id,
            )
            for reference in ordered
        ]
        resolved = await self.repo.resolve_references_for_execution_snapshot(
            tenant_id=tenant_id,
            parent_space_id=space_id,
            references=references,
        )
        if len(resolved) != len(ordered):
            raise BadRequestException(
                "One or more queued Skill revisions are no longer available"
            )

        resolved_by_reference = {
            SkillBindingReference(
                skill_id=binding.skill_id,
                skill_revision_id=binding.skill_revision_id,
            ): binding
            for binding in resolved
        }
        snapshot_bindings: list[ResolvedSkillBinding] = []
        for reference in ordered:
            binding = resolved_by_reference.get(
                SkillBindingReference(
                    skill_id=reference.skill_id,
                    skill_revision_id=reference.skill_revision_id,
                )
            )
            if binding is None:
                raise BadRequestException(
                    "One or more queued Skill revisions are no longer available"
                )
            if (
                binding.revision_number != reference.revision_number
                or binding.content_digest != reference.content_digest
            ):
                raise BadRequestException(
                    "Queued Skill revision metadata no longer matches"
                )
            snapshot_bindings.append(replace(binding, position=reference.position))

        await self._require_execution_allowed(
            tenant_id=tenant_id,
            bindings=snapshot_bindings,
        )
        return compose_skill_instructions(
            base_instructions=base_instructions,
            bindings=snapshot_bindings,
        )

    async def compose_for_policy(
        self, *, policy_id: UUID, base_instructions: str
    ) -> SkillComposition:
        resolution = await self.resolve_governance_bindings_for_runtime(
            policy_id=policy_id
        )
        return compose_skill_instructions(
            base_instructions=base_instructions,
            bindings=list(resolution.eligible),
        )
