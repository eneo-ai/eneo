"""Application service for helper-assistant role assignments.

Owns the lifecycle of role slots in ``org_space_assistant_roles`` — list
the active assignments for a tenant, assign / reassign an assistant to a
role, unassign a role, toggle the ``is_enabled`` / ``is_visible_to_users``
flags, and list the append-only history written to
``help_assistant_assignment_history``.

Enforces the cross-table invariant from PRD §4 ("the assistant filling a
helper role must live in the org-space") and audit-logs every mutation.
All mutations require ``Permission.ADMIN``; ``get_active`` is admin-free
because it drives the availability lookup the prompt-guide modal uses
for every signed-in user.

Reset actions (PRD §7) and archive-replaced helpers (PRD §3, §9) land in
steps 016 / 017 — this file is intentionally limited to CRUD + history
listing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
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
from intric.roles.permissions import Permission, validate_permission
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.assistants.assistant import Assistant
    from intric.assistants.assistant_service import AssistantService
    from intric.audit.application.audit_service import AuditService
    from intric.spaces.space_service import SpaceService


class OrgSpaceAssistantRoleService:
    def __init__(
        self,
        user: UserInDB,
        role_repo: OrgSpaceAssistantRoleRepo,
        history_repo: HelpAssistantAssignmentHistoryRepo,
        assistant_service: "AssistantService",
        space_service: "SpaceService",
        audit_service: "AuditService",
        factory: HelperAssistantsFactory,
    ) -> None:
        self.user = user
        self.role_repo = role_repo
        self.history_repo = history_repo
        self.assistant_service = assistant_service
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

    async def assign(
        self, kind: HelperKind, assistant_id: UUID
    ) -> RoleAssignment:
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
            current.reassign_to(
                assistant_id=assistant_id, actor_user_id=self.user.id
            )
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

    async def toggle_enabled(
        self, kind: HelperKind, value: bool
    ) -> RoleAssignment:
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
            raise BadRequestException(
                f"No active assignment for role '{kind.value}'."
            )

        previous_value = getattr(current, field_label)
        if field_label == "is_enabled":
            current.set_enabled(value=new_value, actor_user_id=self.user.id)
        else:
            current.set_visible_to_users(
                value=new_value, actor_user_id=self.user.id
            )

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
                changes={
                    field_label: {"old": previous_value, "new": new_value}
                },
                extra={
                    "role_kind": kind.value,
                    "role_assignment_id": str(assignment.id),
                    "org_space_id": str(org_space_id),
                },
            ),
        )

        return assignment

    async def _resolve_org_space_id(self) -> UUID:
        org_space = await self.space_service.get_or_create_tenant_space()
        assert org_space.id is not None
        return org_space.id

    async def _load_assistant(self, assistant_id: UUID) -> "Assistant":
        assistant, _ = await self.assistant_service.get_assistant(
            assistant_id=assistant_id
        )
        return assistant
