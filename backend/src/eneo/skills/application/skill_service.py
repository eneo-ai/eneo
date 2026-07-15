from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission, validate_permission
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    Skill,
    SkillComposition,
    SkillExecutionReference,
    SkillHasBindingsError,
    SkillRevision,
    SkillRevisionChange,
    SkillStatusChange,
    compose_skill_instructions,
    create_content_digest,
    normalize_skill_content,
    validate_skill_slug,
)
from eneo.skills.domain.skill_repo import SkillRepo
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService


_SKILL_SLUG_CONSTRAINT = "uq_skills_space_id_slug"


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

    async def list_skills(self, *, space_id: UUID) -> list[Skill]:
        space = await self._space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to read Skills in this Space"
            )
        return await self.repo.list_for_space(space_id=space_id)

    async def get_skill(self, *, skill_id: UUID, require_body: bool = True) -> Skill:
        skill = await self.repo.get(skill_id=skill_id)
        if skill is None:
            raise NotFoundException()
        space = await self._space(skill.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        allowed = actor.can_edit_skills() if require_body else actor.can_read_skills()
        if not allowed:
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
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_create_skills():
            raise UnauthorizedException(
                "You do not have permission to create Skills in this Space"
            )
        normalized_slug = validate_skill_slug(slug)
        name, description, instructions = normalize_skill_content(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        digest = create_content_digest(
            display_name=name,
            description=description,
            instructions=instructions,
        )
        try:
            return await self.repo.create(
                space_id=space_id,
                slug=normalized_slug,
                display_name=name,
                description=description,
                instructions=instructions,
                content_digest=digest,
                created_by_user_id=self.user.id,
            )
        except IntegrityError as error:
            if _SKILL_SLUG_CONSTRAINT in str(error.orig):
                raise NameCollisionException(
                    f"A Skill with slug '{normalized_slug}' already exists in this Space"
                ) from error
            raise

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
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to revise this Skill"
            )
        name, description, instructions = normalize_skill_content(
            display_name=display_name,
            description=description,
            instructions=instructions,
        )
        digest = create_content_digest(
            display_name=name,
            description=description,
            instructions=instructions,
        )
        change = await self.repo.create_revision(
            skill_id=skill.id,
            display_name=name,
            description=description,
            instructions=instructions,
            content_digest=digest,
            created_by_user_id=self.user.id,
        )
        if change is None:
            raise NotFoundException()
        return change

    async def list_revisions(self, *, skill_id: UUID) -> list[SkillRevision]:
        skill = await self.get_skill(skill_id=skill_id)
        return await self.repo.list_revisions(skill_id=skill.id)

    async def set_active(self, *, skill_id: UUID, is_active: bool) -> SkillStatusChange:
        skill = await self.get_skill(skill_id=skill_id)
        space = await self._space(skill.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to change this Skill"
            )
        change = await self.repo.set_active(skill_id=skill.id, is_active=is_active)
        if change is None:
            raise NotFoundException()
        return change

    async def delete_skill(self, *, skill_id: UUID) -> Skill:
        skill = await self.get_skill(skill_id=skill_id)
        space = await self._space(skill.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_delete_skills():
            raise UnauthorizedException(
                "You do not have permission to delete this Skill"
            )
        try:
            deleted = await self.repo.delete(skill_id=skill.id)
        except SkillHasBindingsError as error:
            raise NameCollisionException(
                "This Skill is still attached. Remove every binding before deleting it."
            ) from error
        except IntegrityError as error:
            raise NameCollisionException(
                "This Skill became attached while it was being deleted. "
                "Remove every binding and try again."
            ) from error
        if deleted is None:
            raise NotFoundException()
        return deleted

    @staticmethod
    def _validate_reference_count(references: list[tuple[UUID, UUID]]) -> None:
        max_bindings = get_settings().skill_max_bindings
        if len(references) > max_bindings:
            raise BadRequestException(
                f"A resource cannot use more than {max_bindings} Skills"
            )
        if len({skill_id for skill_id, _ in references}) != len(references):
            raise BadRequestException("A Skill can only be attached once")
        if len(set(references)) != len(references):
            raise BadRequestException("Duplicate Skill revision binding")

    async def _resolve_references(
        self,
        *,
        space_id: UUID,
        references: list[tuple[UUID, UUID]],
        existing: list[ResolvedSkillBinding],
    ) -> list[ResolvedSkillBinding]:
        self._validate_reference_count(references)
        resolved = await self.repo.resolve_references_for_binding_update(
            space_id=space_id, references=references
        )
        if len(resolved) != len(references):
            raise NotFoundException(
                "One or more Skill revisions do not exist in this Space"
            )
        existing_pairs = {
            (binding.skill_id, binding.skill_revision_id) for binding in existing
        }
        inactive_new = [
            binding
            for binding in resolved
            if not binding.is_active
            and (binding.skill_id, binding.skill_revision_id) not in existing_pairs
        ]
        if inactive_new:
            raise BadRequestException("Inactive Skills cannot receive new bindings")
        return resolved

    async def list_assistant_bindings(
        self, *, space_id: UUID, assistant_id: UUID
    ) -> list[ResolvedSkillBinding]:
        space = await self._space(space_id)
        assistant = space.get_assistant(assistant_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_assistants():
            raise UnauthorizedException(
                "You do not have permission to edit this Assistant"
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

    async def replace_assistant_bindings(
        self,
        *,
        space_id: UUID,
        assistant_id: UUID,
        references: list[tuple[UUID, UUID]],
    ) -> list[ResolvedSkillBinding]:
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
        if not await self.repo.lock_assistant_for_binding_update(
            assistant_id=assistant_id
        ):
            raise NotFoundException()
        existing = await self.repo.list_assistant_bindings(assistant_id=assistant_id)
        resolved = await self._resolve_references(
            space_id=space_id, references=references, existing=existing
        )
        await self.repo.replace_assistant_bindings(
            assistant_id=assistant_id,
            space_id=space_id,
            bindings=resolved,
        )
        return resolved

    async def list_app_bindings(
        self, *, space_id: UUID, app_id: UUID
    ) -> list[ResolvedSkillBinding]:
        space = await self._space(space_id)
        space.get_app(app_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_apps():
            raise UnauthorizedException("You do not have permission to edit this App")
        if not actor.can_read_skills():
            raise UnauthorizedException(
                "You do not have permission to read Skills in this Space"
            )
        return await self.repo.list_app_bindings(app_id=app_id)

    async def replace_app_bindings(
        self,
        *,
        space_id: UUID,
        app_id: UUID,
        references: list[tuple[UUID, UUID]],
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
        resolved = await self._resolve_references(
            space_id=space_id, references=references, existing=existing
        )
        await self.repo.replace_app_bindings(
            app_id=app_id,
            space_id=space_id,
            bindings=resolved,
        )
        return resolved

    async def replace_governance_bindings(
        self,
        *,
        policy_id: UUID,
        organization_space_id: UUID,
        references: list[tuple[UUID, UUID]],
    ) -> list[ResolvedSkillBinding]:
        if self.user.active_api_key is not None:
            raise UnauthorizedException("Skill policy changes require a session token")
        validate_permission(self.user, Permission.ADMIN)
        space = await self._space(organization_space_id)
        if not space.is_organization() or space.tenant_id != self.user.tenant_id:
            raise BadRequestException(
                "Governance Skills must belong to this tenant's organisation Space"
            )
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_skills():
            raise UnauthorizedException(
                "You do not have permission to configure organisation Skills"
            )
        existing = await self.repo.list_policy_bindings(policy_id=policy_id)
        resolved = await self._resolve_references(
            space_id=organization_space_id,
            references=references,
            existing=existing,
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

    async def compose_for_assistant(
        self, *, assistant_id: UUID, base_instructions: str
    ) -> SkillComposition:
        bindings = await self.repo.list_assistant_bindings(assistant_id=assistant_id)
        return compose_skill_instructions(
            base_instructions=base_instructions, bindings=bindings
        )

    async def compose_for_app(
        self, *, app_id: UUID, base_instructions: str
    ) -> SkillComposition:
        bindings = await self.repo.list_app_bindings(app_id=app_id)
        return compose_skill_instructions(
            base_instructions=base_instructions, bindings=bindings
        )

    async def compose_for_execution_snapshot(
        self,
        *,
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
            (reference.skill_id, reference.skill_revision_id) for reference in ordered
        ]
        resolved = await self.repo.resolve_references(
            space_id=space_id,
            references=references,
        )
        if len(resolved) != len(ordered):
            raise BadRequestException(
                "One or more queued Skill revisions are no longer available"
            )

        resolved_by_reference = {
            (binding.skill_id, binding.skill_revision_id): binding
            for binding in resolved
        }
        snapshot_bindings: list[ResolvedSkillBinding] = []
        for reference in ordered:
            binding = resolved_by_reference.get(
                (reference.skill_id, reference.skill_revision_id)
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

        return compose_skill_instructions(
            base_instructions=base_instructions,
            bindings=snapshot_bindings,
        )

    async def compose_for_policy(
        self, *, policy_id: UUID, base_instructions: str
    ) -> SkillComposition:
        bindings = await self.repo.list_policy_bindings(policy_id=policy_id)
        return compose_skill_instructions(
            base_instructions=base_instructions, bindings=bindings
        )
