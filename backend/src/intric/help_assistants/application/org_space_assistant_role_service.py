"""Application service for helper-assistant role assignments.

Owns the lifecycle of role slots in ``org_space_assistant_roles`` — list
the active assignments for a tenant, assign / reassign an assistant to a
role, unassign a role, toggle the ``is_enabled`` / ``is_visible_to_users``
flags, list the append-only history written to
``help_assistant_assignment_history``, and run the two admin reset
actions (PRD §7).

Enforces the cross-table invariant from PRD §4 ("the assistant filling a
helper role must live in the org-space") and audit-logs every mutation.
All mutations require ``Permission.ADMIN``; ``get_active`` is admin-free
because it drives the availability lookup the prompt-guide modal uses
for every signed-in user.

The two reset paths consume :mod:`intric.help_assistants.defaults` — the
single runtime source of truth for shipped Help Assistant config — so the
admin UI cannot drift from what the team ships.

Archive-replaced helpers (PRD §3, §9) routes hard-deletion through
``assistant_service.delete_assistant`` so existing cleanup paths
(e.g. the API-key scope revoker) run; the FK on
``help_assistant_assignment_history.assistant_id`` is ``ON DELETE SET NULL``,
so history rows survive with ``assistant_name_snapshot`` intact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.help_assistants.defaults import get_defaults
from intric.help_assistants.domain.assignment_history import AssignmentHistory
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.factory import HelperAssistantsFactory
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.role_assignment import RoleAssignment
from intric.help_assistants.infrastructure.help_assistant_assignment_history_repo import (  # noqa: E501
    HelpAssistantAssignmentHistoryRepo,
)
from intric.help_assistants.infrastructure.org_space_assistant_role_repo import (
    OrgSpaceAssistantRoleRepo,
)
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permission
from intric.users.user import UserInDB, UserSparse

if TYPE_CHECKING:
    from intric.assistants.assistant_repo import AssistantRepository
    from intric.assistants.assistant_service import AssistantService
    from intric.audit.application.audit_service import AuditService
    from intric.completion_models.application import CompletionModelCRUDService
    from intric.prompts.prompt_service import PromptService
    from intric.spaces.space_service import SpaceService
    from intric.users.user_repo import UsersRepository


logger = get_logger(__name__)


class OrgSpaceAssistantRoleService:
    def __init__(
        self,
        user: UserInDB,
        role_repo: OrgSpaceAssistantRoleRepo,
        history_repo: HelpAssistantAssignmentHistoryRepo,
        assistant_service: "AssistantService",
        assistant_repo: "AssistantRepository",
        prompt_service: "PromptService",
        users_repo: "UsersRepository",
        completion_model_crud_service: "CompletionModelCRUDService",
        space_service: "SpaceService",
        audit_service: "AuditService",
        factory: HelperAssistantsFactory,
    ) -> None:
        self.user = user
        self.role_repo = role_repo
        self.history_repo = history_repo
        self.assistant_service = assistant_service
        self.assistant_repo = assistant_repo
        self.prompt_service = prompt_service
        self.users_repo = users_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.space_service = space_service
        self.audit_service = audit_service
        self.factory = factory

    async def list_for_calling_tenant(self) -> list[RoleAssignment]:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()
        return await self.role_repo.list_for_org_space(org_space_id=org_space_id)

    async def get_active(self, kind: HelperKind) -> RoleAssignment | None:
        org_space_id = await self._resolve_org_space_id()
        return await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )

    async def list_history(self, kind: HelperKind) -> list[AssignmentHistory]:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()
        return await self.history_repo.list_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )

    async def assign(self, kind: HelperKind, assistant_id: UUID) -> RoleAssignment:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        assistant = await self._load_assistant(assistant_id)
        if assistant.space_id != org_space_id:
            raise BadRequestException("Assistant must live in the org-space.")

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )

        previous_assistant_id: UUID | None = None
        if current is not None:
            if current.assistant_id == assistant_id:
                # Idempotent: same assistant already fills the slot.
                return current

            previous_assistant_id = current.assistant_id
            old_assistant = await self._load_assistant(previous_assistant_id)
            history_entry = self.factory.create_assignment_history_entry(
                org_space_id=org_space_id,
                kind=kind,
                assistant_id=previous_assistant_id,
                assistant_name_snapshot=old_assistant.name,
                replaced_by_assistant_id=assistant_id,
                reason=AssignmentHistoryReason.REASSIGNED,
                actor_user_id=self.user.id,
            )
            await self.history_repo.add(history_entry)
            current.reassign_to(assistant_id=assistant_id, actor_user_id=self.user.id)
            assignment = await self.role_repo.update(current)
        else:
            new_role = self.factory.create_role_assignment(
                org_space_id=org_space_id,
                kind=kind,
                assistant_id=assistant_id,
                created_by_user_id=self.user.id,
                updated_by_user_id=self.user.id,
            )
            assignment = await self.role_repo.add(new_role)

        assert assignment.id is not None
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_ROLE_ASSIGNED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant_id,
            description=(
                f"Assigned assistant '{assistant.name}' to help-assistant "
                f"role '{kind.value}'"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=assistant,
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(assignment.id),
                    "org_space_id": str(org_space_id),
                    "previous_assistant_id": (
                        str(previous_assistant_id)
                        if previous_assistant_id is not None
                        else None
                    ),
                },
            ),
        )

        return assignment

    async def unassign(self, kind: HelperKind) -> None:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if current is None:
            return

        assert current.id is not None
        old_assistant = await self._load_assistant(current.assistant_id)

        history_entry = self.factory.create_assignment_history_entry(
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=current.assistant_id,
            assistant_name_snapshot=old_assistant.name,
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.UNASSIGNED,
            actor_user_id=self.user.id,
        )
        await self.history_repo.add(history_entry)
        await self.role_repo.delete(id=current.id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_ROLE_UNASSIGNED,
            entity_type=EntityType.ASSISTANT,
            entity_id=current.assistant_id,
            description=(
                f"Unassigned help-assistant role '{kind.value}' "
                f"(previously '{old_assistant.name}')"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=old_assistant,
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(current.id),
                    "org_space_id": str(org_space_id),
                },
            ),
        )

    async def toggle_enabled(self, kind: HelperKind, value: bool) -> RoleAssignment:
        validate_permission(self.user, Permission.ADMIN)
        return await self._toggle(
            kind=kind,
            new_value=value,
            field_label="is_enabled",
            action=ActionType.HELP_ASSISTANT_ROLE_TOGGLED_ENABLED,
        )

    async def toggle_visible_to_users(
        self, kind: HelperKind, value: bool
    ) -> RoleAssignment:
        validate_permission(self.user, Permission.ADMIN)
        return await self._toggle(
            kind=kind,
            new_value=value,
            field_label="is_visible_to_users",
            action=ActionType.HELP_ASSISTANT_ROLE_TOGGLED_VISIBLE,
        )

    async def _toggle(
        self,
        *,
        kind: HelperKind,
        new_value: bool,
        field_label: str,
        action: ActionType,
    ) -> RoleAssignment:
        org_space_id = await self._resolve_org_space_id()

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if current is None:
            raise BadRequestException(f"No active assignment for role '{kind.value}'.")

        previous_value = getattr(current, field_label)
        if field_label == "is_enabled":
            current.set_enabled(value=new_value, actor_user_id=self.user.id)
        else:
            current.set_visible_to_users(value=new_value, actor_user_id=self.user.id)

        assignment = await self.role_repo.update(current)
        assert assignment.id is not None

        assistant = await self._load_assistant(assignment.assistant_id)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.ASSISTANT,
            entity_id=assignment.assistant_id,
            description=(
                f"Toggled '{field_label}' to {new_value} on help-assistant "
                f"role '{kind.value}'"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=assistant,
                changes={field_label: {"old": previous_value, "new": new_value}},
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(assignment.id),
                    "org_space_id": str(org_space_id),
                },
            ),
        )

        return assignment

    async def reset_instructions_only(self, kind: HelperKind) -> Assistant:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if current is None:
            raise BadRequestException(f"No active assignment for role '{kind.value}'.")

        system_user_id = await self._resolve_system_user_id()
        defaults = get_defaults(kind)

        # Explicit ownership: the new prompt must be attributed to the
        # tenant's system user (the helper-assistant owner), not the calling
        # admin — the audit log records the admin separately. ``_add_prompt``
        # is the same flip-is_selected path that ``assistant_service.update_assistant``
        # uses internally; we go through the repo directly so we can pass the
        # prompt we just created instead of letting ``update_assistant``
        # create a second one (and attribute it via its own owner rules).
        new_prompt = await self.prompt_service.create_prompt(
            text=defaults.prompt_text,
            description="Reset to shipped default",
            owner_user_id=system_user_id,
        )
        assert new_prompt is not None
        await self.assistant_repo._add_prompt(  # pyright: ignore[reportPrivateUsage]
            assistant_id=current.assistant_id, prompt=new_prompt
        )

        assistant = await self._load_assistant(current.assistant_id)
        assert current.id is not None
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_RESET_INSTRUCTIONS,
            entity_type=EntityType.ASSISTANT,
            entity_id=current.assistant_id,
            description=(
                f"Reset instructions to shipped default for help-assistant "
                f"role '{kind.value}'"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=assistant,
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(current.id),
                    "org_space_id": str(org_space_id),
                    "new_prompt_id": str(new_prompt.id),
                },
            ),
        )

        return assistant

    async def reset_to_default(self, kind: HelperKind) -> Assistant:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if current is None:
            raise BadRequestException(f"No active assignment for role '{kind.value}'.")

        old_assistant_id = current.assistant_id
        old_assistant = await self._load_assistant(old_assistant_id)
        old_assistant_name = old_assistant.name

        system_user_id = await self._resolve_system_user_id()
        defaults = get_defaults(kind)

        completion_model = (
            await self.completion_model_crud_service.get_default_completion_model()
        )
        if completion_model is None:
            logger.warning(
                "Tenant %s has no eligible completion model; resetting "
                "help-assistant role '%s' with completion_model_id=NULL — an "
                "admin must pick one before the helper can run.",
                self.user.tenant_id,
                kind.value,
            )

        new_prompt = await self.prompt_service.create_prompt(
            text=defaults.prompt_text,
            description=defaults.description,
            owner_user_id=system_user_id,
        )
        assert new_prompt is not None

        # Build the entity directly: ``AssistantFactory.create_assistant``
        # round-trips through ``UserInDB`` → ``UserSparse.model_validate``,
        # and the system user's reserved-TLD email (``system+<tid>@eneo.local``)
        # fails that validation. ``model_construct`` skips validators so we
        # can carry the system_user_id through the entity into the repo
        # without touching production email validators.
        new_assistant_id = uuid4()
        system_user_sparse = UserSparse.model_construct(
            id=system_user_id,
            email=f"system+{self.user.tenant_id}@eneo.local",
            username=f"system+{self.user.tenant_id}",
        )
        new_assistant = Assistant(
            id=new_assistant_id,
            user=system_user_sparse,
            space_id=org_space_id,
            completion_model=completion_model,
            name=defaults.name,
            prompt=new_prompt,
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=defaults.logging_enabled,
            websites=[],
            collections=[],
            attachments=[],
            published=False,
            description=defaults.description,
            insight_enabled=defaults.insight_enabled,
            data_retention_days=defaults.data_retention_days,
        )
        await self.assistant_repo.add(new_assistant)

        current.reassign_to(assistant_id=new_assistant_id, actor_user_id=self.user.id)
        assignment = await self.role_repo.update(current)
        assert assignment.id is not None

        history_entry = self.factory.create_assignment_history_entry(
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=old_assistant_id,
            assistant_name_snapshot=old_assistant_name,
            replaced_by_assistant_id=new_assistant_id,
            reason=AssignmentHistoryReason.RESET_TO_DEFAULT,
            actor_user_id=self.user.id,
        )
        await self.history_repo.add(history_entry)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_RESET_TO_DEFAULT,
            entity_type=EntityType.ASSISTANT,
            entity_id=new_assistant_id,
            description=(
                f"Reset help-assistant role '{kind.value}' to shipped "
                f"default (previous: '{old_assistant_name}')"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=new_assistant,
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(assignment.id),
                    "org_space_id": str(org_space_id),
                    "previous_assistant_id": str(old_assistant_id),
                    "previous_assistant_name": old_assistant_name,
                    "new_prompt_id": str(new_prompt.id),
                },
            ),
        )

        return new_assistant

    async def list_archivable_helpers(self, kind: HelperKind) -> list[Assistant]:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        replaced_ids = await self.history_repo.list_replaced_assistant_ids_by_org_space(
            org_space_id=org_space_id
        )
        active_assignments = await self.role_repo.list_for_org_space(
            org_space_id=org_space_id
        )
        active_ids = {a.assistant_id for a in active_assignments if a.kind == kind}
        archivable_ids = replaced_ids - active_ids

        assistants: list[Assistant] = []
        for assistant_id in archivable_ids:
            assistant = await self._load_assistant(assistant_id)
            assistants.append(assistant)
        return assistants

    async def archive_helper(self, assistant_id: UUID) -> None:
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        replaced_ids = await self.history_repo.list_replaced_assistant_ids_by_org_space(
            org_space_id=org_space_id
        )
        if assistant_id not in replaced_ids:
            raise BadRequestException(
                "Assistant is not an archivable helper for this org-space."
            )

        active_assignments = await self.role_repo.list_for_org_space(
            org_space_id=org_space_id
        )
        if assistant_id in {a.assistant_id for a in active_assignments}:
            raise BadRequestException(
                "Assistant is currently assigned to a help-assistant role; "
                "reassign or unassign the role before archiving."
            )

        # Capture the name before the row is gone so the audit entry stays
        # meaningful once ``assistant_id`` is NULL on every history row.
        assistant = await self._load_assistant(assistant_id)
        assistant_name_snapshot = assistant.name

        await self.assistant_service.delete_assistant(assistant_id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_ARCHIVED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant_id,
            description=(f"Archived helper assistant '{assistant_name_snapshot}'"),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=assistant,
                extra={
                    "assistant_name_snapshot": assistant_name_snapshot,
                    "org_space_id": str(org_space_id),
                },
            ),
        )

    async def _resolve_org_space_id(self) -> UUID:
        org_space = await self.space_service.get_or_create_tenant_space()
        assert org_space.id is not None
        return org_space.id

    async def _resolve_system_user_id(self) -> UUID:
        system_user_id = await self.users_repo.get_system_user_id_for_tenant(
            tenant_id=self.user.tenant_id
        )
        if system_user_id is None:
            raise BadRequestException(
                "Tenant is missing its system user; the help-assistant seed "
                "migration has not run for this tenant."
            )
        return system_user_id

    async def _load_assistant(self, assistant_id: UUID) -> Assistant:
        assistant, _ = await self.assistant_service.get_assistant(
            assistant_id=assistant_id
        )
        return assistant
