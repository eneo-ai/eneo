"""Factory for Help-Assistant domain entities.

Mirrors the ``AssistantFactory`` shape: a thin coordinator that produces
domain entities from explicit kwargs. Repos call the ``create_*`` methods
to map a DB row into an entity; services call them to construct fresh
entities (``id=None``, ``created_at=None``) before persistence.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from intric.help_assistants.domain.assignment_history import AssignmentHistory
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.helper_run import HelperRun
from intric.help_assistants.domain.helper_run_status import HelperRunStatus
from intric.help_assistants.domain.role_assignment import RoleAssignment


class HelperAssistantsFactory:
    def create_role_assignment(
        self,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID,
        is_enabled: bool = True,
        is_visible_to_users: bool = True,
        created_by_user_id: UUID | None = None,
        updated_by_user_id: UUID | None = None,
        id: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> RoleAssignment:
        return RoleAssignment(
            id=id,
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=assistant_id,
            is_enabled=is_enabled,
            is_visible_to_users=is_visible_to_users,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    def create_assignment_history_entry(
        self,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID | None,
        assistant_name_snapshot: str,
        replaced_by_assistant_id: UUID | None,
        reason: AssignmentHistoryReason,
        actor_user_id: UUID | None,
        replaced_at: datetime | None = None,
        id: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> AssignmentHistory:
        return AssignmentHistory(
            id=id,
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=assistant_id,
            assistant_name_snapshot=assistant_name_snapshot,
            replaced_by_assistant_id=replaced_by_assistant_id,
            reason=reason,
            actor_user_id=actor_user_id,
            replaced_at=replaced_at,
            created_at=created_at,
            updated_at=updated_at,
        )

    def create_helper_run(
        self,
        tenant_id: UUID,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID | None,
        target_type: str,
        target_id: UUID,
        session_id: UUID,
        actor_user_id: UUID | None,
        status: HelperRunStatus = HelperRunStatus.IN_PROGRESS,
        completed_at: datetime | None = None,
        id: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> HelperRun:
        return HelperRun(
            id=id,
            tenant_id=tenant_id,
            org_space_id=org_space_id,
            kind=kind,
            assistant_id=assistant_id,
            target_type=target_type,
            target_id=target_id,
            session_id=session_id,
            actor_user_id=actor_user_id,
            status=status,
            completed_at=completed_at,
            created_at=created_at,
            updated_at=updated_at,
        )
