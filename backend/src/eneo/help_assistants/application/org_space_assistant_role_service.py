"""Application service for helper-assistant role assignments.

Owns the lifecycle of role slots in ``org_space_assistant_roles`` — list the
active assignments for a tenant, install / uninstall a shipped Help Assistant
template, and toggle the ``is_enabled`` / ``is_visible_to_users`` flags.

Help Assistants are not preseeded. An admin installs a template from the admin
UI (``install_helper``), which creates the underlying assistant (owned by the
per-tenant system user, living in the org-space) populated from the template —
including its shipped instructions — plus the active role row.
``uninstall_helper`` reverses that — it removes the role and hard-deletes the
assistant so the template becomes available to add again.

Enforces the cross-table invariant from PRD §4 ("the assistant filling a
helper role must live in the org-space") and audit-logs every mutation. All
mutations require ``Permission.ADMIN``; ``get_active`` is admin-free because it
drives the availability lookup the prompt-guide modal uses for every signed-in
user.

The installable templates come from :mod:`eneo.help_assistants.templates` —
the single code-owned registry of shipped Help Assistants. Templates carry
identity + invariants only; instructions are pasted by the admin afterwards.

``uninstall_helper`` routes hard-deletion through
``assistant_service.delete_assistant`` so existing cleanup paths (e.g. the
API-key scope revoker) run; the FK on
``help_assistant_assignment_history.assistant_id`` is ``ON DELETE SET NULL``,
so the history row written before deletion survives with
``assistant_name_snapshot`` intact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.role_assignment import RoleAssignment
from eneo.help_assistants.infrastructure.help_assistant_assignment_history_repo import (  # noqa: E501
    HelpAssistantAssignmentHistoryRepo,
)
from eneo.help_assistants.infrastructure.org_space_assistant_role_repo import (
    OrgSpaceAssistantRoleRepo,
)
from eneo.help_assistants.templates import (
    HelperAssistantTemplate,
    get_template,
    list_templates,
)
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB, UserSparse

if TYPE_CHECKING:
    from eneo.assistants.assistant_repo import AssistantRepository
    from eneo.assistants.assistant_service import AssistantService
    from eneo.audit.application.audit_service import AuditService
    from eneo.completion_models.application import CompletionModelCRUDService
    from eneo.prompts.prompt_service import PromptService
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user_repo import UsersRepository


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

    async def list_available_templates(
        self,
    ) -> list[tuple[HelperKind, HelperAssistantTemplate]]:
        """Shipped templates not yet installed for the calling tenant.

        Drives the admin "Add help assistant" picker: a template drops out of
        the list once its kind has an active role, and reappears after the
        helper is uninstalled.
        """
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()
        active = await self.role_repo.list_for_org_space(org_space_id=org_space_id)
        installed_kinds = {role.kind for role in active}
        return [
            (kind, template)
            for kind, template in list_templates()
            if kind not in installed_kinds
        ]

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

    async def install_helper(self, kind: HelperKind) -> RoleAssignment:
        """Install a shipped Help Assistant template into the tenant.

        Creates the underlying assistant — owned by the per-tenant system
        user, living in the org-space — populated from the template, including
        its shipped instructions, then the active role assignment. The helper
        starts enabled and visible to users: the shipped prompt is what makes
        it render the structured Q&A on assistant settings pages, so it is
        usable as soon as it is added. Refuses to install a kind that is
        already installed.
        """
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        existing = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if existing is not None:
            raise BadRequestException(
                f"Help assistant '{kind.value}' is already installed."
            )

        template = get_template(kind)
        system_user_id = await self._resolve_system_user_id()

        completion_model = (
            await self.completion_model_crud_service.get_default_completion_model()
        )
        if completion_model is None:
            logger.warning(
                "Tenant %s has no eligible completion model; installing "
                "help-assistant '%s' with completion_model_id=NULL — an admin "
                "must pick one before the helper can run.",
                self.user.tenant_id,
                kind.value,
            )

        # Ship the template's instructions: the Prompt Guide's prompt is what
        # drives the eneo-question Q&A rendering on assistant settings pages,
        # so every install (and re-install after a delete) reproduces it.
        new_prompt = await self.prompt_service.create_prompt(
            text=template.prompt_text,
            description=None,
            owner_user_id=system_user_id,
        )
        assert new_prompt is not None

        # Build the entity directly: ``AssistantFactory.create_assistant``
        # round-trips through ``UserSparse.model_validate``, and the system
        # user's reserved-TLD email (``system+<tid>@eneo.local``) fails that
        # validation. ``model_construct`` skips validators so we can carry the
        # system_user_id through the entity into the repo.
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
            name=template.name,
            prompt=new_prompt,
            completion_model_kwargs=ModelKwargs(),
            logging_enabled=template.logging_enabled,
            websites=[],
            collections=[],
            attachments=[],
            published=False,
            description=template.description,
            insight_enabled=template.insight_enabled,
            data_retention_days=template.data_retention_days,
        )
        await self.assistant_repo.add(new_assistant)

        assignment = self.factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=new_assistant_id,
            is_enabled=True,
            is_visible_to_users=True,
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
        )
        assignment = await self.role_repo.add(assignment)
        assert assignment.id is not None

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_INSTALLED,
            entity_type=EntityType.ASSISTANT,
            entity_id=new_assistant_id,
            description=(
                f"Installed help-assistant '{template.name}' (role '{kind.value}')"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=new_assistant,
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(assignment.id),
                    "org_space_id": str(org_space_id),
                    "new_prompt_id": str(new_prompt.id),
                },
            ),
        )

        return assignment

    async def uninstall_helper(self, kind: HelperKind) -> None:
        """Uninstall the active Help Assistant for ``kind``.

        Removes the role assignment and hard-deletes the underlying assistant
        so the template becomes available to add again. Writes an append-only
        history row (``reason=UNASSIGNED``) before deletion so the audit trail
        and the ``ask_guard`` "former helper" check keep a name snapshot.
        """
        validate_permission(self.user, Permission.ADMIN)
        org_space_id = await self._resolve_org_space_id()

        current = await self.role_repo.get_by_org_space_and_kind(
            org_space_id=org_space_id, kind=kind
        )
        if current is None:
            raise BadRequestException(
                f"No active assignment for help assistant '{kind.value}'."
            )
        assert current.id is not None

        assistant_id = current.assistant_id
        assistant = await self._load_assistant(assistant_id)
        assistant_name_snapshot = assistant.name

        history_entry = self.factory.create_assignment_history_entry(
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=assistant_id,
            assistant_name_snapshot=assistant_name_snapshot,
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.UNASSIGNED,
            actor_user_id=self.user.id,
        )
        await self.history_repo.add(history_entry)

        # The role's ``assistant_id`` FK is ``ON DELETE RESTRICT``, so the role
        # row must go before the assistant it points at.
        await self.role_repo.delete(current.id)
        await self.assistant_service.delete_assistant(assistant_id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.HELP_ASSISTANT_UNINSTALLED,
            entity_type=EntityType.ASSISTANT,
            entity_id=assistant_id,
            description=(
                f"Uninstalled help-assistant '{assistant_name_snapshot}' "
                f"(role '{kind.value}')"
            ),
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=assistant,
                extra={
                    "role_kind": kind.value,
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
                "Tenant is missing its system user; the help-assistant "
                "infrastructure migration has not run for this tenant."
            )
        return system_user_id

    async def _load_assistant(self, assistant_id: UUID) -> Assistant:
        assistant, _ = await self.assistant_service.get_assistant(
            assistant_id=assistant_id
        )
        return assistant
