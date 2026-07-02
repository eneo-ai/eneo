from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.flows.application.flow_run_lifecycle_events import (
    emit_flow_run_terminalization_event,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowAuditActorFields, FlowPrincipal

logger = logging.getLogger(__name__)


class FlowRunTerminalizationInvariantError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlowRunTerminalizationResult:
    run: FlowRun
    did_transition: bool
    target_status: FlowRunStatus
    source: FlowRunLifecycleSource
    audit_outbox_id: UUID | None


class FlowRunTerminalizer:
    def __init__(
        self,
        flow_run_repo: FlowRunRepository,
        flow_run_rerun_repo: FlowRunRerunRepository,
        audit_outbox_repo: FlowRunAuditOutboxRepository,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
    ):
        self.flow_run_repo = flow_run_repo
        self.flow_run_rerun_repo = flow_run_rerun_repo
        self.audit_outbox_repo = audit_outbox_repo
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo

    async def terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
        principal: FlowPrincipal | None = None,
    ) -> FlowRunTerminalizationResult:
        return await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            source=source,
            error=error,
            output_payload_json=output_payload_json,
            cancelled_at=cancelled_at,
            principal=principal,
            stale_before=None,
        )

    async def terminalize_stale_running_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        stale_before: datetime,
        error: FlowRunError,
    ) -> FlowRunTerminalizationResult:
        return await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
            error=error,
            stale_before=stale_before,
        )

    async def _terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
        principal: FlowPrincipal | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRunTerminalizationResult:
        if not is_terminal_flow_run_status(target_status):
            raise ValueError("target_status must be a terminal FlowRunStatus")
        if error is not None and error.source is not None and error.source != source:
            raise FlowRunTerminalizationInvariantError(
                "Flow run error source must match terminalization source."
            )

        effective_error_code = error.code if error is not None else None
        effective_error_message = error.message if error is not None else None

        existing_run = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id)
        if is_terminal_flow_run_status(existing_run.status):
            emit_flow_run_terminalization_event(
                run=existing_run,
                outcome="noop_already_terminal",
                source=source,
                target_status=target_status,
                previous_status=existing_run.status,
                audit_outbox_id=None,
                error_code=effective_error_code,
            )
            return FlowRunTerminalizationResult(
                run=existing_run,
                did_transition=False,
                target_status=target_status,
                source=source,
                audit_outbox_id=None,
            )
        previous_status = existing_run.status

        if target_status == FlowRunStatus.COMPLETED:
            active_results = await self.flow_run_repo.count_active_step_results(
                run_id=run_id,
                tenant_id=tenant_id,
            )
            open_attempts = await self.flow_run_repo.count_open_step_attempts(
                run_id=run_id,
                tenant_id=tenant_id,
            )
            if active_results or open_attempts:
                raise FlowRunTerminalizationInvariantError(
                    "Cannot complete a flow run with active step results or open attempts."
                )

        terminal_run = await self.flow_run_repo.terminalize_run_status(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            error=error,
            output_payload_json=output_payload_json,
            cancelled_at=cancelled_at,
            stale_before=stale_before,
        )
        if terminal_run is None:
            existing_run = await self.flow_run_repo.get(
                run_id=run_id, tenant_id=tenant_id
            )
            emit_flow_run_terminalization_event(
                run=existing_run,
                outcome="noop_lost_race",
                source=source,
                target_status=target_status,
                previous_status=previous_status,
                audit_outbox_id=None,
                error_code=effective_error_code,
            )
            return FlowRunTerminalizationResult(
                run=existing_run,
                did_transition=False,
                target_status=target_status,
                source=source,
                audit_outbox_id=None,
            )

        if target_status == FlowRunStatus.FAILED:
            await self.flow_run_repo.close_active_step_results_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepResultStatus.FAILED,
                error_code=effective_error_code,
                error_message=effective_error_message,
            )
            await self.flow_run_repo.close_open_step_attempts_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepAttemptStatus.FAILED,
                error_code=effective_error_code,
                error_message=effective_error_message,
            )
        elif target_status == FlowRunStatus.CANCELLED:
            await self.flow_run_repo.close_active_step_results_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepResultStatus.CANCELLED,
                error_code=effective_error_code,
                error_message=effective_error_message,
            )
            await self.flow_run_repo.close_open_step_attempts_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepAttemptStatus.CANCELLED,
                error_code=effective_error_code,
                error_message=effective_error_message,
            )

        await self.flow_run_rerun_repo.close_active_rerun_operations_for_terminal_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            error_code=effective_error_code,
            error_message=effective_error_message,
        )

        checkpoint_principal = self._principal_or_none_from_run(
            run=terminal_run,
            principal=principal,
        )
        if target_status == FlowRunStatus.CANCELLED:
            await self.flow_run_review_checkpoint_repo.cancel_active_review_checkpoint_for_terminal_run(
                tenant_id=tenant_id,
                flow_run_id=run_id,
                run_revision=terminal_run.revision,
                principal=checkpoint_principal,
                error_code=effective_error_code,
                error_message=effective_error_message,
            )

        actor_fields = self._audit_actor_fields(
            run=terminal_run,
            principal=principal,
            source=source,
        )
        action = self._action_for_status(target_status)
        outbox_id = await self.audit_outbox_repo.insert_terminal_audit_outbox(
            run=terminal_run,
            action=action,
            actor_id=actor_fields["actor_id"],
            actor_type=actor_fields["actor_type"],
            actor_api_key_id=actor_fields["actor_api_key_id"],
            source=source,
            target_status=target_status,
            error_code=effective_error_code,
            error_message=effective_error_message,
        )
        emit_flow_run_terminalization_event(
            run=terminal_run,
            outcome="transitioned",
            source=source,
            target_status=target_status,
            previous_status=previous_status,
            audit_outbox_id=outbox_id,
            error_code=effective_error_code,
        )
        return FlowRunTerminalizationResult(
            run=terminal_run,
            did_transition=True,
            target_status=target_status,
            source=source,
            audit_outbox_id=outbox_id,
        )

    @staticmethod
    def _action_for_status(status: FlowRunStatus) -> ActionType:
        if status == FlowRunStatus.COMPLETED:
            return ActionType.FLOW_RUN_COMPLETED
        if status == FlowRunStatus.FAILED:
            return ActionType.FLOW_RUN_FAILED
        if status == FlowRunStatus.CANCELLED:
            return ActionType.FLOW_RUN_CANCELLED
        raise ValueError("target_status must be terminal")

    @staticmethod
    def _principal_or_none_from_run(
        *, run: FlowRun, principal: FlowPrincipal | None
    ) -> FlowPrincipal | None:
        if principal is not None:
            return principal
        try:
            return FlowPrincipal.from_run(run)
        except ValueError:
            return None

    @staticmethod
    def _audit_actor_fields(
        *, run: FlowRun, principal: FlowPrincipal | None, source: FlowRunLifecycleSource
    ) -> FlowAuditActorFields:
        resolved = FlowRunTerminalizer._principal_or_none_from_run(
            run=run,
            principal=principal,
        )
        if resolved is None:
            logger.warning(
                "flow_run_terminalization.audit_actor_fallback run_id=%s tenant_id=%s source=%s",
                run.id,
                run.tenant_id,
                source.value,
            )
            return {
                "actor_id": None,
                "actor_type": ActorType.SYSTEM,
                "actor_api_key_id": None,
            }
        return resolved.audit_actor_fields()
