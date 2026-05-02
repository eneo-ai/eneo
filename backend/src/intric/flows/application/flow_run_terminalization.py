from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.flows.domain.flow import FlowRun, FlowRunStatus, JsonObject
from intric.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from intric.flows.flow import FlowStepAttemptStatus, FlowStepResultStatus
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.principal import FlowAuditActorFields, FlowPrincipal

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
    def __init__(self, flow_run_repo: FlowRunRepository):
        self.flow_run_repo = flow_run_repo

    async def terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error_code: str | None = None,
        error_message: str | None = None,
        output_payload_json: JsonObject | None = None,
        cancelled_at: datetime | None = None,
        principal: FlowPrincipal | None = None,
    ) -> FlowRunTerminalizationResult:
        return await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            source=source,
            error_code=error_code,
            error_message=error_message,
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
        error_code: str,
        error_message: str,
    ) -> FlowRunTerminalizationResult:
        return await self._terminalize_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
            error_code=error_code,
            error_message=error_message,
            stale_before=stale_before,
        )

    async def _terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error_code: str | None = None,
        error_message: str | None = None,
        output_payload_json: JsonObject | None = None,
        cancelled_at: datetime | None = None,
        principal: FlowPrincipal | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRunTerminalizationResult:
        if not is_terminal_flow_run_status(target_status):
            raise ValueError("target_status must be a terminal FlowRunStatus")

        existing_run = await self.flow_run_repo.get(run_id=run_id, tenant_id=tenant_id)
        if is_terminal_flow_run_status(existing_run.status):
            return FlowRunTerminalizationResult(
                run=existing_run,
                did_transition=False,
                target_status=target_status,
                source=source,
                audit_outbox_id=None,
            )

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
            error_message=error_message,
            output_payload_json=output_payload_json,
            cancelled_at=cancelled_at,
            stale_before=stale_before,
        )
        if terminal_run is None:
            existing_run = await self.flow_run_repo.get(
                run_id=run_id, tenant_id=tenant_id
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
                error_message=error_message,
            )
            await self.flow_run_repo.close_open_step_attempts_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepAttemptStatus.FAILED,
                error_code=error_code or source.value,
                error_message=error_message,
            )
        elif target_status == FlowRunStatus.CANCELLED:
            await self.flow_run_repo.close_active_step_results_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepResultStatus.CANCELLED,
                error_message=error_message,
            )
            await self.flow_run_repo.close_open_step_attempts_for_terminal_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowStepAttemptStatus.CANCELLED,
                error_code=error_code or source.value,
                error_message=error_message,
            )

        await self.flow_run_repo.close_active_rerun_operations_for_terminal_run(
            run_id=run_id,
            tenant_id=tenant_id,
            target_status=target_status,
            error_code=error_code or source.value,
            error_message=error_message,
        )

        actor_fields = self._audit_actor_fields(
            run=terminal_run,
            principal=principal,
            source=source,
        )
        action = self._action_for_status(target_status)
        outbox_id = await self.flow_run_repo.insert_terminal_audit_outbox(
            run=terminal_run,
            description=f"{action.value}:{source.value}",
            action=action,
            entity_type=EntityType.FLOW_RUN,
            actor_id=actor_fields["actor_id"],
            actor_type=actor_fields["actor_type"],
            actor_api_key_id=actor_fields["actor_api_key_id"],
            source=source,
            target_status=target_status,
            error_code=error_code,
            error_message=error_message,
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
    def _audit_actor_fields(
        *, run: FlowRun, principal: FlowPrincipal | None, source: FlowRunLifecycleSource
    ) -> FlowAuditActorFields:
        resolved = principal
        if resolved is None:
            try:
                resolved = FlowPrincipal.from_run(run)
            except ValueError:
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
