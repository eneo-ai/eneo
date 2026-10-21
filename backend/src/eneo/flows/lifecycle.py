"""Atomic terminal state and audit writes, using the existing audit service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.flow_models import FlowRunStatus, ReviewCheckpointState

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.flows.flow_repo import FlowRepository
    from eneo.users.user import UserInDB

ACTIVE = (FlowRunStatus.QUEUED, FlowRunStatus.RUNNING, FlowRunStatus.AWAITING_REVIEW)


async def finish_run(
    repo: FlowRepository,
    audit_service: AuditService | None,
    run_id: UUID,
    tenant_id: UUID,
    status: FlowRunStatus,
    *,
    error: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    expected_statuses: tuple[FlowRunStatus, ...] = ACTIVE,
    user: UserInDB | None = None,
    expired: bool = False,
) -> bool:
    """Caller owns the short transaction; a losing writer emits no audit."""
    run = await repo.get_run(run_id, tenant_id)
    if run is None:
        return False
    moved = await repo.update_run_status(
        run_id,
        status,
        error=error,
        output_payload_json=output,
        expected_statuses=expected_statuses,
    )
    if not moved:
        return False
    if status != FlowRunStatus.COMPLETED:
        checkpoint = await repo.get_active_checkpoint(run_id)
        if checkpoint is not None:
            await repo.decide_checkpoint(
                checkpoint.id,
                state=ReviewCheckpointState.EXPIRED
                if expired
                else ReviewCheckpointState.CANCELLED,
                from_states=(
                    ReviewCheckpointState.AWAITING_REVIEW,
                    ReviewCheckpointState.EDITED,
                    ReviewCheckpointState.APPROVED,
                ),
            )
        await repo.cancel_pending_step_results(run_id)
        await repo.fail_running_step_results(
            run_id,
            error_code=(error or {}).get("code", "flow_run_cancelled"),
            error_message="The run ended before this step finished.",
        )
        await repo.mark_started_attempts_outcome_unknown(run_id)
    if audit_service is not None:
        action = {
            FlowRunStatus.COMPLETED: ActionType.FLOW_RUN_COMPLETED,
            FlowRunStatus.FAILED: ActionType.FLOW_RUN_FAILED,
            FlowRunStatus.CANCELLED: ActionType.FLOW_RUN_CANCELLED,
        }[status]
        extra = {
            "flow_id": str(run.flow_id),
            "flow_version": run.flow_version,
            "error_code": (error or {}).get("code"),
        }
        await audit_service.log(
            tenant_id=tenant_id,
            action=action,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run_id,
            description=f"Flow run {status.value}",
            user=user,
            actor_type=ActorType.SYSTEM,
            metadata=(
                AuditMetadata.standard(actor=user, target=run, extra=extra)
                if user
                else AuditMetadata.system_action(
                    "Flow run terminalized", target=run, extra=extra
                )
            ),
        )
    return True
