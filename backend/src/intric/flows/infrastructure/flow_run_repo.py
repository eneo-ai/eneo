from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, TypedDict, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.principal_types import PrincipalType
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.database.tables.tenant_table import Tenants
from intric.files.file_models import FileType
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    JsonObject,
)
from intric.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunTerminalSource,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_run_rerun_graph import RerunInvalidatedStep
from intric.flows.flow_run_step_result_file import (
    FlowRunStepResultFile,
    FlowRunStepResultFileAvailability,
    FlowRunStepResultFileSource,
)
from intric.flows.principal import FlowPrincipal
from intric.main.exceptions import BadRequestException, NotFoundException


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int


class StepInputFileProjection(TypedDict):
    step_id: UUID
    step_order: int
    file_ids: Sequence[UUID]


@dataclass(frozen=True, slots=True)
class FlowRunRerunCommandResult:
    operation: FlowRunRerunOperation
    run: FlowRun
    invalidated_steps: tuple[FlowRunRerunInvalidatedStep, ...]
    created: bool


@dataclass(frozen=True, slots=True)
class FlowRunActiveRerunOperation:
    operation: FlowRunRerunOperation
    invalidated_steps: tuple[FlowRunRerunInvalidatedStep, ...]


_RERUN_ELIGIBLE_RUN_STATUSES = (
    FlowRunStatus.COMPLETED.value,
    FlowRunStatus.FAILED.value,
)
_ACTIVE_RERUN_OPERATION_STATUSES = (
    FlowRunRerunOperationStatus.QUEUED.value,
    FlowRunRerunOperationStatus.RUNNING.value,
)

_RERUN_STEP_RESULT_RESET_VALUES: dict[str, object] = {
    "status": FlowStepResultStatus.PENDING.value,
    "current_attempt_no": None,
    "input_payload_json": None,
    "output_payload_json": None,
    "effective_prompt": None,
    "model_parameters_json": None,
    "num_tokens_input": None,
    "num_tokens_output": None,
    "error_message": None,
    "flow_step_execution_hash": None,
    "tool_calls_metadata": None,
    "started_at": None,
    "finished_at": None,
}


class FlowRunRepository:
    """Tenant-scoped repository for flow run lifecycle and run evidence."""

    _ACTIVE_STATUSES = tuple(status.value for status in ACTIVE_FLOW_RUN_STATUSES)
    _OPEN_ATTEMPT_STATUSES = (
        FlowStepAttemptStatus.STARTED.value,
        FlowStepAttemptStatus.RETRIED.value,
    )
    _ACTIVE_STEP_RESULT_STATUSES = (
        FlowStepResultStatus.PENDING.value,
        FlowStepResultStatus.RUNNING.value,
    )

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def create(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        user_id: UUID | None,
        principal_type: str = "user",
        principal_user_id: UUID | None = None,
        principal_api_key_id: UUID | None = None,
        tenant_id: UUID,
        input_payload_json: dict[str, Any] | None,
        preseed_steps: Sequence["PreseedStep"],
        step_input_files: Sequence["StepInputFileProjection"] | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> FlowRun:
        if principal_type == PrincipalType.USER.value and principal_user_id is None:
            principal_user_id = user_id
        run_row = await self.session.scalar(
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                user_id=user_id,
                principal_type=principal_type,
                principal_user_id=principal_user_id,
                principal_api_key_id=principal_api_key_id,
                tenant_id=tenant_id,
                trace_id=uuid4(),
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                status=FlowRunStatus.QUEUED.value,
                input_payload_json=input_payload_json,
            )
            .returning(FlowRuns)
        )
        if run_row is None:
            raise NotFoundException("Could not create flow run.")

        preseed_rows = [
            {
                "flow_run_id": run_row.id,
                "flow_id": flow_id,
                "tenant_id": tenant_id,
                "step_id": step["step_id"],
                "step_order": step["step_order"],
                "assistant_id": step["assistant_id"],
                "status": FlowStepResultStatus.PENDING.value,
            }
            for step in sorted(preseed_steps, key=lambda item: int(item["step_order"]))
        ]
        if preseed_rows:
            await self.session.execute(sa.insert(FlowStepResults).values(preseed_rows))

        step_input_file_rows = [
            {
                "flow_run_id": run_row.id,
                "flow_id": flow_id,
                "tenant_id": tenant_id,
                "step_id": projection["step_id"],
                "step_order": projection["step_order"],
                "attempt_no": 1,
                "file_id": file_id,
                "ordinal": ordinal,
            }
            for projection in sorted(
                step_input_files or (),
                key=lambda item: (int(item["step_order"]), str(item["step_id"])),
            )
            for ordinal, file_id in enumerate(projection["file_ids"])
        ]
        if step_input_file_rows:
            await self.session.execute(
                sa.insert(FlowRunStepInputFiles).values(step_input_file_rows)
            )

        return self.factory.from_flow_run_db(run_row)

    async def get(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        flow_id: UUID | None = None,
    ) -> FlowRun:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        run_row = await self.session.scalar(stmt)
        if run_row is None:
            raise NotFoundException("Flow run not found.")
        return self.factory.from_flow_run_db(run_row)

    async def get_latest_completed_attempt_id_for_step(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
    ) -> UUID | None:
        attempt_id = await self.session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.flow_id == flow_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.status == FlowStepAttemptStatus.COMPLETED.value)
            .order_by(FlowStepAttempts.attempt_no.desc())
            .limit(1)
        )
        return attempt_id

    async def accept_or_replay_rerun_operation(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        rerun_step_id: UUID,
        rerun_step_order: int,
        request_fingerprint: str,
        expected_run_revision: int,
        reason: str,
        input_payload_json: JsonObject | None,
        step_inputs_json: JsonObject | None,
        requested_by_user_id: UUID,
        invalidated_steps: Sequence[RerunInvalidatedStep],
    ) -> FlowRunRerunCommandResult:
        existing_operation = await self._get_rerun_operation_row(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            request_fingerprint=request_fingerprint,
        )
        if existing_operation is not None:
            return await self._rerun_command_result_from_row(
                operation_row=existing_operation,
                created=False,
            )

        run_row = await self.session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_row is None:
            raise NotFoundException("Flow run not found.")

        existing_operation = await self._get_rerun_operation_row(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            request_fingerprint=request_fingerprint,
        )
        if existing_operation is not None:
            return await self._rerun_command_result_from_row(
                operation_row=existing_operation,
                created=False,
            )

        if run_row.revision != expected_run_revision:
            raise BadRequestException(
                "Flow run revision is stale.",
                code="flow_run_rerun_stale_revision",
                context={
                    "expected_run_revision": expected_run_revision,
                    "current_run_revision": run_row.revision,
                },
            )
        if run_row.status not in _RERUN_ELIGIBLE_RUN_STATUSES:
            raise BadRequestException(
                "Flow run is not eligible for rerun.",
                code="flow_run_rerun_invalid_transition",
                context={"status": run_row.status},
            )

        ordered_invalidated_steps = tuple(
            sorted(invalidated_steps, key=lambda step: step.step_order)
        )
        root_invalidated_step = next(
            (
                step
                for step in ordered_invalidated_steps
                if step.step_id == rerun_step_id and step.step_order == rerun_step_order
            ),
            None,
        )
        if root_invalidated_step is None:
            raise BadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code="flow_run_rerun_step_not_found",
            )

        invalidated_step_ids = [step.step_id for step in ordered_invalidated_steps]
        current_results = await self._current_step_results_by_step_id(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            step_ids=invalidated_step_ids,
        )
        missing_current_result_step_ids = [
            step.step_id
            for step in ordered_invalidated_steps
            if step.step_id not in current_results
        ]
        if missing_current_result_step_ids:
            raise BadRequestException(
                "Rerun graph has no current result for every invalidated step.",
                code="flow_run_rerun_step_incomplete",
                context={
                    "step_ids": [
                        str(step_id) for step_id in missing_current_result_step_ids
                    ],
                },
            )
        root_current_result = current_results.get(rerun_step_id)
        if (
            root_current_result is None
            or root_current_result.status != FlowStepResultStatus.COMPLETED.value
        ):
            raise BadRequestException(
                "Rerun step has no completed current result.",
                code="flow_run_rerun_step_incomplete",
            )

        latest_completed_attempts = await self._latest_completed_attempts_by_step_id(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            step_ids=invalidated_step_ids,
        )
        root_attempt_no = await self._next_attempt_no(
            tenant_id=tenant_id,
            flow_run_id=flow_run_id,
            step_id=rerun_step_id,
        )
        operation_row = await self.session.scalar(
            pg_insert(FlowRunRerunOperations)
            .values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=flow_run_id,
                rerun_step_id=rerun_step_id,
                rerun_step_order=rerun_step_order,
                root_attempt_no=root_attempt_no,
                root_attempt_id=None,
                status=FlowRunRerunOperationStatus.QUEUED.value,
                request_fingerprint=request_fingerprint,
                expected_run_revision=expected_run_revision,
                accepted_run_revision=run_row.revision,
                reason=reason,
                input_payload_json=input_payload_json,
                step_inputs_json=step_inputs_json,
                requested_by_principal_type=PrincipalType.USER.value,
                requested_by_user_id=requested_by_user_id,
                failure_code=None,
                failure_message=None,
                started_at=None,
                finished_at=None,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_run_rerun_operations_request_fingerprint",
            )
            .returning(FlowRunRerunOperations)
        )
        if operation_row is None:
            operation_row = await self._get_rerun_operation_row(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=flow_run_id,
                request_fingerprint=request_fingerprint,
            )
            if operation_row is None:
                raise NotFoundException("Could not create or fetch rerun operation.")
            return await self._rerun_command_result_from_row(
                operation_row=operation_row,
                created=False,
            )

        invalidated_rows = [
            {
                "operation_id": operation_row.id,
                "tenant_id": tenant_id,
                "flow_id": flow_id,
                "flow_run_id": flow_run_id,
                "step_id": invalidated_step.step_id,
                "step_order": invalidated_step.step_order,
                "invalidation_order": invalidation_order,
                "role": (
                    FlowRunRerunInvalidationRole.ROOT.value
                    if invalidated_step.step_id == rerun_step_id
                    else FlowRunRerunInvalidationRole.DOWNSTREAM.value
                ),
                "dependency_sources_json": (
                    []
                    if invalidated_step.step_id == rerun_step_id
                    else [
                        dependency_kind.value
                        for dependency_kind in invalidated_step.dependency_kinds
                    ]
                ),
                "prior_step_result_id": current_results[invalidated_step.step_id].id,
                "prior_attempt_id": (
                    latest_completed_attempts[invalidated_step.step_id].id
                    if invalidated_step.step_id in latest_completed_attempts
                    else None
                ),
                "new_attempt_no": None,
                "new_attempt_id": None,
            }
            for invalidation_order, invalidated_step in enumerate(
                ordered_invalidated_steps,
                start=1,
            )
        ]
        if invalidated_rows:
            await self.session.execute(
                sa.insert(FlowRunRerunInvalidatedSteps).values(invalidated_rows)
            )

        await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.flow_id == flow_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.step_id.in_(invalidated_step_ids))
            .values(**_RERUN_STEP_RESULT_RESET_VALUES)
        )
        updated_run_row = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(
                status=FlowRunStatus.QUEUED.value,
                revision=run_row.revision + 1,
                output_payload_json=None,
                error_message=None,
                started_at=None,
                finished_at=None,
                cancelled_at=None,
            )
            .returning(FlowRuns)
        )
        if updated_run_row is None:
            raise NotFoundException("Flow run not found.")

        return await self._rerun_command_result_from_row(
            operation_row=operation_row,
            run_row=updated_run_row,
            created=True,
        )

    async def get_idempotent_run(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        idempotency_key: str,
        principal: FlowPrincipal | None = None,
        user_id: UUID | None = None,
    ) -> tuple[FlowRun, str | None] | None:
        if principal is None:
            if user_id is None:
                raise ValueError("principal or user_id is required")
            principal = FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=user_id,
            )
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.idempotency_key == idempotency_key)
            .where(FlowRuns.principal_type == principal.principal_type.value)
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal.principal_user_id)
        if principal.principal_api_key_id is not None:
            stmt = stmt.where(
                FlowRuns.principal_api_key_id == principal.principal_api_key_id
            )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return self.factory.from_flow_run_db(row), row.request_fingerprint

    async def count_active_runs(self, *, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
        )
        return int(count or 0)

    async def acquire_tenant_run_creation_lock(self, *, tenant_id: UUID) -> None:
        await self.session.execute(
            sa.select(Tenants.id).where(Tenants.id == tenant_id).with_for_update()
        )

    async def list_runs(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID | None = None,
        principal_user_id: UUID | None = None,
        principal_api_key_id: UUID | None = None,
        user_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .order_by(FlowRuns.created_at.desc())
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        resolved_principal_user_id = principal_user_id or user_id
        if resolved_principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == resolved_principal_user_id)
        if principal_api_key_id is not None:
            stmt = stmt.where(FlowRuns.principal_api_key_id == principal_api_key_id)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_stale_queued_runs(
        self,
        *,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        if run_id is not None:
            stmt = stmt.where(FlowRuns.id == run_id)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_stale_running_runs(
        self,
        *,
        tenant_id: UUID,
        stale_before: datetime,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.RUNNING.value)
            .where(FlowRuns.updated_at <= stale_before)
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def claim_stale_queued_run_for_redispatch(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
    ) -> FlowRun | None:
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        claimed = await self.session.scalar(
            stmt.values(updated_at=datetime.now(timezone.utc)).returning(FlowRuns)
        )
        if claimed is None:
            return None
        return self.factory.from_flow_run_db(claimed)

    async def terminalize_run_status(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        error_message: str | None = None,
        output_payload_json: JsonObject | None = None,
        cancelled_at: datetime | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRun | None:
        if target_status not in TERMINAL_FLOW_RUN_STATUSES:
            raise ValueError("target_status must be terminal")

        values: dict[str, Any] = {
            "status": target_status.value,
            "error_message": error_message,
            "output_payload_json": output_payload_json,
            "finished_at": datetime.now(timezone.utc),
        }
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at

        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
        )
        if stale_before is not None:
            stmt = stmt.where(FlowRuns.updated_at <= stale_before)
        run_row = await self.session.scalar(stmt.values(**values).returning(FlowRuns))
        if run_row is None:
            return None
        return self.factory.from_flow_run_db(run_row)

    async def count_active_step_results(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(self._ACTIVE_STEP_RESULT_STATUSES))
        )
        return int(count or 0)

    async def count_open_step_attempts(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(self._OPEN_ATTEMPT_STATUSES))
        )
        return int(count or 0)

    async def close_active_step_results_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepResultStatus,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(self._ACTIVE_STEP_RESULT_STATUSES))
            .values(
                status=target_status.value,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def close_active_rerun_operations_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> int:
        if target_status not in TERMINAL_FLOW_RUN_STATUSES:
            raise ValueError("target_status must be terminal")

        values: dict[str, Any] = {
            "status": FlowRunRerunOperationStatus(target_status.value).value,
            "finished_at": datetime.now(timezone.utc),
        }
        if target_status == FlowRunStatus.COMPLETED:
            values["failure_code"] = None
            values["failure_message"] = None
        else:
            values["failure_code"] = error_code
            values["failure_message"] = error_message

        result = await self.session.execute(
            sa.update(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .where(FlowRunRerunOperations.status.in_(_ACTIVE_RERUN_OPERATION_STATUSES))
            .values(**values)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def close_open_step_attempts_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepAttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(self._OPEN_ATTEMPT_STATUSES))
            .values(
                status=target_status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def insert_terminal_audit_outbox(
        self,
        *,
        run: FlowRun,
        description: str,
        action: ActionType,
        entity_type: EntityType,
        actor_id: UUID | None,
        actor_type: ActorType,
        actor_api_key_id: UUID | None,
        source: FlowRunTerminalSource,
        target_status: FlowRunStatus,
        error_code: str | None,
        error_message: str | None,
    ) -> UUID:
        outbox_id = await self.session.scalar(
            sa.insert(FlowRunAuditOutbox)
            .values(
                tenant_id=run.tenant_id,
                flow_id=run.flow_id,
                flow_run_id=run.id,
                run_revision=run.revision,
                description=description,
                action=action.value,
                entity_type=entity_type.value,
                entity_id=run.id,
                actor_id=actor_id,
                actor_type=actor_type.value,
                actor_api_key_id=actor_api_key_id,
                source=source.value,
                target_status=target_status.value,
                error_code=error_code,
                error_message=error_message,
            )
            .returning(FlowRunAuditOutbox.id)
        )
        if outbox_id is None:
            raise RuntimeError("Flow run audit outbox insert did not return an id.")
        return outbox_id

    async def update_input_payload(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        input_payload_json: dict[str, Any],
    ) -> None:
        # Merge-patch under row lock to avoid clobbering concurrent key updates.
        current_payload = await self.session.scalar(
            sa.select(FlowRuns.input_payload_json)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        merged_payload = dict(current_payload or {})
        merged_payload.update(dict(input_payload_json))
        await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(input_payload_json=merged_payload)
        )

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepResult]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == run_id)
                    .where(FlowStepResults.tenant_id == tenant_id)
                    .order_by(FlowStepResults.step_order.asc())
                )
            )
            .scalars()
            .all()
        )
        return [self.factory.from_flow_step_result_db(row) for row in rows]

    async def list_step_attempts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepAttempt]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == run_id)
                    .where(FlowStepAttempts.tenant_id == tenant_id)
                    .order_by(
                        FlowStepAttempts.step_order.asc(),
                        FlowStepAttempts.attempt_no.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self.factory.from_flow_step_attempt_db(row) for row in rows]

    async def list_rerun_operations_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowRunRerunOperation]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunOperations)
                    .where(FlowRunRerunOperations.flow_run_id == run_id)
                    .where(FlowRunRerunOperations.tenant_id == tenant_id)
                    .order_by(
                        FlowRunRerunOperations.created_at.asc(),
                        FlowRunRerunOperations.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self.factory.from_flow_run_rerun_operation_db(row) for row in rows]

    async def list_rerun_invalidated_steps_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowRunRerunInvalidatedStep]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunInvalidatedSteps)
                    .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
                    .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
                    .order_by(
                        FlowRunRerunInvalidatedSteps.operation_id.asc(),
                        FlowRunRerunInvalidatedSteps.invalidation_order.asc(),
                        FlowRunRerunInvalidatedSteps.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            self.factory.from_flow_run_rerun_invalidated_step_db(row) for row in rows
        ]

    async def list_result_files(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowRunStepResultFile]:
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .order_by(
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            _result_file_from_rows(result_file_row, file_row)
            for result_file_row, file_row in rows
        ]

    async def list_result_files_for_runs(
        self,
        *,
        run_ids: Sequence[UUID],
        tenant_id: UUID,
    ) -> list[FlowRunStepResultFile]:
        unique_run_ids = list(dict.fromkeys(run_ids))
        if not unique_run_ids:
            return []
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id.in_(unique_run_ids))
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .order_by(
                FlowRunStepResultFiles.flow_run_id.asc(),
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            _result_file_from_rows(result_file_row, file_row)
            for result_file_row, file_row in rows
        ]

    async def get_result_file(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        file_id: UUID,
    ) -> FlowRunStepResultFile | None:
        stmt = (
            sa.select(FlowRunStepResultFiles, Files)
            .join(Files, Files.id == FlowRunStepResultFiles.file_id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .where(FlowRunStepResultFiles.file_id == file_id)
            .order_by(
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.attempt_no.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        result_file_row, file_row = row
        return _result_file_from_rows(result_file_row, file_row)

    async def mark_running_if_claimable(self, *, run_id: UUID, tenant_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .values(
                status=FlowRunStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def get_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        row = await self.session.scalar(
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def get_active_rerun_operation(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> FlowRunActiveRerunOperation | None:
        operation_rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunOperations)
                    .where(FlowRunRerunOperations.flow_run_id == run_id)
                    .where(FlowRunRerunOperations.flow_id == flow_id)
                    .where(FlowRunRerunOperations.tenant_id == tenant_id)
                    .where(
                        FlowRunRerunOperations.status.in_(
                            _ACTIVE_RERUN_OPERATION_STATUSES
                        )
                    )
                    .order_by(FlowRunRerunOperations.created_at.desc())
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if not operation_rows:
            return None
        if len(operation_rows) > 1:
            raise BadRequestException(
                "Flow run has multiple active rerun operations.",
                code="flow_run_rerun_active_operation_conflict",
            )
        operation_row = operation_rows[0]
        invalidated_rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunInvalidatedSteps)
                    .where(
                        FlowRunRerunInvalidatedSteps.operation_id == operation_row.id
                    )
                    .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
                    .order_by(FlowRunRerunInvalidatedSteps.invalidation_order.asc())
                )
            )
            .scalars()
            .all()
        )
        return FlowRunActiveRerunOperation(
            operation=self.factory.from_flow_run_rerun_operation_db(operation_row),
            invalidated_steps=tuple(
                self.factory.from_flow_run_rerun_invalidated_step_db(row)
                for row in invalidated_rows
            ),
        )

    async def claim_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        now_utc = datetime.now(timezone.utc)
        row = await self.session.scalar(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(
                FlowStepResults.status.in_(
                    (
                        FlowStepResultStatus.PENDING.value,
                        FlowStepResultStatus.FAILED.value,
                    )
                )
            )
            .values(
                status=FlowStepResultStatus.RUNNING.value,
                error_message=None,
                started_at=sa.func.coalesce(FlowStepResults.started_at, now_utc),
                finished_at=None,
            )
            .returning(FlowStepResults)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def allocate_next_attempt_no(
        self,
        *,
        tenant_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
    ) -> int:
        return await self._next_attempt_no(
            tenant_id=tenant_id,
            flow_run_id=flow_run_id,
            step_id=step_id,
        )

    async def create_or_get_attempt_started(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        celery_task_id: str | None,
        rerun_operation_id: UUID | None = None,
        predecessor_attempt_id: UUID | None = None,
    ) -> FlowStepAttempt:
        started_at = datetime.now(timezone.utc)
        insert_stmt = (
            pg_insert(FlowStepAttempts)
            .values(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                celery_task_id=celery_task_id,
                rerun_operation_id=rerun_operation_id,
                predecessor_attempt_id=predecessor_attempt_id,
                status=FlowStepAttemptStatus.STARTED.value,
                started_at=started_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_step_attempts_run_step_attempt",
            )
            .returning(FlowStepAttempts)
        )
        row = await self.session.scalar(insert_stmt)
        if row is None:
            row = await self.session.scalar(
                sa.select(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.step_id == step_id)
                .where(FlowStepAttempts.attempt_no == attempt_no)
                .where(FlowStepAttempts.tenant_id == tenant_id)
            )
        if row is None:
            raise NotFoundException("Could not create or fetch flow step attempt.")
        return self.factory.from_flow_step_attempt_db(row)

    async def finish_attempt(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        status: FlowStepAttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        requested_model: str | None = None,
        response_model: str | None = None,
        provider: str | None = None,
        finish_reason: str | None = None,
        provider_response_id: str | None = None,
        num_tokens_input: int | None = None,
        num_tokens_output: int | None = None,
        provenance_json: dict[str, Any] | None = None,
    ) -> FlowStepAttempt | None:
        row = await self.session.scalar(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(
                FlowStepAttempts.status.in_(
                    (
                        FlowStepAttemptStatus.STARTED.value,
                        FlowStepAttemptStatus.RETRIED.value,
                    )
                )
            )
            .values(
                status=status.value,
                error_code=error_code,
                error_message=error_message,
                requested_model=requested_model,
                response_model=response_model,
                provider=provider,
                finish_reason=finish_reason,
                provider_response_id=provider_response_id,
                num_tokens_input=num_tokens_input,
                num_tokens_output=num_tokens_output,
                provenance_json=provenance_json,
                finished_at=datetime.now(timezone.utc),
            )
            .returning(FlowStepAttempts)
        )
        if row is None:
            return None
        if status == FlowStepAttemptStatus.COMPLETED:
            await self._mark_predecessor_superseded_by_attempt(
                completed_attempt_row=row,
                tenant_id=tenant_id,
            )
        return self.factory.from_flow_step_attempt_db(row)

    async def mark_rerun_operation_running(
        self,
        *,
        operation_id: UUID,
        tenant_id: UUID,
        root_attempt_id: UUID | None = None,
    ) -> None:
        now_utc = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "status": FlowRunRerunOperationStatus.RUNNING.value,
            "started_at": sa.func.coalesce(
                FlowRunRerunOperations.started_at,
                now_utc,
            ),
        }
        if root_attempt_id is not None:
            values["root_attempt_id"] = root_attempt_id
        await self.session.execute(
            sa.update(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.id == operation_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .where(
                FlowRunRerunOperations.status
                == FlowRunRerunOperationStatus.QUEUED.value
            )
            .values(**values)
        )

    async def link_rerun_invalidated_step_attempt(
        self,
        *,
        operation_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        new_attempt_no: int,
        new_attempt_id: UUID,
    ) -> None:
        result = await self.session.execute(
            sa.update(FlowRunRerunInvalidatedSteps)
            .where(FlowRunRerunInvalidatedSteps.operation_id == operation_id)
            .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
            .where(FlowRunRerunInvalidatedSteps.step_id == step_id)
            .where(
                sa.or_(
                    FlowRunRerunInvalidatedSteps.new_attempt_id.is_(None),
                    FlowRunRerunInvalidatedSteps.new_attempt_id == new_attempt_id,
                )
            )
            .values(new_attempt_no=new_attempt_no, new_attempt_id=new_attempt_id)
        )
        if int(getattr(result, "rowcount", 0) or 0) == 0:
            raise BadRequestException(
                "Rerun invalidated step is already linked to another attempt.",
                code="flow_run_rerun_attempt_lineage_conflict",
            )

    async def _get_rerun_operation_row(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        request_fingerprint: str,
    ) -> FlowRunRerunOperations | None:
        return await self.session.scalar(
            sa.select(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .where(FlowRunRerunOperations.flow_id == flow_id)
            .where(FlowRunRerunOperations.flow_run_id == flow_run_id)
            .where(FlowRunRerunOperations.request_fingerprint == request_fingerprint)
        )

    async def _rerun_command_result_from_row(
        self,
        *,
        operation_row: FlowRunRerunOperations,
        created: bool,
        run_row: FlowRuns | None = None,
    ) -> FlowRunRerunCommandResult:
        resolved_run_row = run_row
        if resolved_run_row is None:
            resolved_run_row = await self.session.scalar(
                sa.select(FlowRuns)
                .where(FlowRuns.id == operation_row.flow_run_id)
                .where(FlowRuns.flow_id == operation_row.flow_id)
                .where(FlowRuns.tenant_id == operation_row.tenant_id)
            )
        if resolved_run_row is None:
            raise NotFoundException("Flow run not found.")

        invalidated_rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunInvalidatedSteps)
                    .where(
                        FlowRunRerunInvalidatedSteps.operation_id == operation_row.id
                    )
                    .where(
                        FlowRunRerunInvalidatedSteps.tenant_id
                        == operation_row.tenant_id
                    )
                    .order_by(FlowRunRerunInvalidatedSteps.invalidation_order.asc())
                )
            )
            .scalars()
            .all()
        )
        return FlowRunRerunCommandResult(
            operation=self.factory.from_flow_run_rerun_operation_db(operation_row),
            run=self.factory.from_flow_run_db(resolved_run_row),
            invalidated_steps=tuple(
                self.factory.from_flow_run_rerun_invalidated_step_db(row)
                for row in invalidated_rows
            ),
            created=created,
        )

    async def _current_step_results_by_step_id(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        step_ids: Sequence[UUID],
    ) -> dict[UUID, FlowStepResults]:
        if not step_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepResults)
                    .where(FlowStepResults.flow_run_id == flow_run_id)
                    .where(FlowStepResults.flow_id == flow_id)
                    .where(FlowStepResults.tenant_id == tenant_id)
                    .where(FlowStepResults.step_id.in_(step_ids))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        return {row.step_id: row for row in rows if row.step_id is not None}

    async def _latest_completed_attempts_by_step_id(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        flow_run_id: UUID,
        step_ids: Sequence[UUID],
    ) -> dict[UUID, FlowStepAttempts]:
        if not step_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowStepAttempts)
                    .where(FlowStepAttempts.flow_run_id == flow_run_id)
                    .where(FlowStepAttempts.flow_id == flow_id)
                    .where(FlowStepAttempts.tenant_id == tenant_id)
                    .where(FlowStepAttempts.step_id.in_(step_ids))
                    .where(
                        FlowStepAttempts.status == FlowStepAttemptStatus.COMPLETED.value
                    )
                    .order_by(
                        FlowStepAttempts.step_id.asc(),
                        FlowStepAttempts.attempt_no.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        latest_attempts: dict[UUID, FlowStepAttempts] = {}
        for row in rows:
            if row.step_id is None or row.step_id in latest_attempts:
                continue
            latest_attempts[row.step_id] = row
        return latest_attempts

    async def _next_attempt_no(
        self,
        *,
        tenant_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
    ) -> int:
        max_attempt_no = await self.session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(FlowStepAttempts.attempt_no), 0))
            .where(FlowStepAttempts.flow_run_id == flow_run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.step_id == step_id)
        )
        return int(max_attempt_no or 0) + 1

    async def _mark_predecessor_superseded_by_attempt(
        self,
        *,
        completed_attempt_row: FlowStepAttempts,
        tenant_id: UUID,
    ) -> None:
        if completed_attempt_row.predecessor_attempt_id is None:
            return
        await self.session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.id == completed_attempt_row.predecessor_attempt_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(
                sa.or_(
                    FlowStepAttempts.superseded_by_attempt_id.is_(None),
                    FlowStepAttempts.superseded_by_attempt_id
                    == completed_attempt_row.id,
                )
            )
            .values(superseded_by_attempt_id=completed_attempt_row.id)
        )


def _result_file_from_rows(
    result_file_row: FlowRunStepResultFiles,
    file_row: Files,
) -> FlowRunStepResultFile:
    return FlowRunStepResultFile(
        flow_run_id=result_file_row.flow_run_id,
        flow_id=result_file_row.flow_id,
        tenant_id=result_file_row.tenant_id,
        step_result_id=result_file_row.step_result_id,
        step_id=result_file_row.step_id,
        step_order=result_file_row.step_order,
        attempt_no=result_file_row.attempt_no,
        file_id=result_file_row.file_id,
        ordinal=result_file_row.ordinal,
        source=cast(FlowRunStepResultFileSource, result_file_row.source),
        name=file_row.name,
        checksum=file_row.checksum,
        size=file_row.size,
        mimetype=file_row.mimetype,
        file_type=FileType(file_row.file_type),
        availability=_file_availability(file_row),
    )


def _file_availability(file_row: Files) -> FlowRunStepResultFileAvailability:
    if file_row.blob is not None or file_row.text is not None:
        return "available"
    return "content_purged"
