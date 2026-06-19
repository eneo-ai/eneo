"""Persistence owner for Flow run rerun operations and invalidated-step lineage.

Callers own the active database transaction. Accepting a rerun operation also
resets the affected run and step-result state inside that transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunStepInputOverride,
)
from intric.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from intric.flows.domain.rerun_exceptions import (
    FlowRunRerunAttemptLineageConflictError,
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunMultipleActiveOperationsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStaleRevisionError,
    FlowRunRerunStepInputsInvalidError,
    FlowRunRerunStepNotFoundError,
)
from intric.flows.enums import (
    RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
)
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_run_input_envelope import (
    RerunInputOverride,
    build_rerun_execution_input_envelope,
)
from intric.flows.flow_run_rerun_graph import RerunInvalidatedStep
from intric.flows.infrastructure.flow_run_step_input_file_rows import (
    build_step_input_file_rows,
    insert_step_input_file_rows,
)
from intric.flows.infrastructure.flow_step_attempt_numbering import (
    next_step_attempt_no,
)
from intric.flows.principal import FlowPrincipal


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
    "started_at": None,
    "finished_at": None,
}
_RerunStepInputKey = tuple[UUID, UUID, UUID, UUID, int]


def _rerun_step_input_key(row: FlowRunRerunOperations) -> _RerunStepInputKey:
    return (
        row.flow_run_id,
        row.flow_id,
        row.tenant_id,
        row.rerun_step_id,
        row.root_attempt_no,
    )


class FlowRunRerunRepository:
    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

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
        rerun_input_override: RerunInputOverride,
        requested_by_principal: FlowPrincipal,
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
            raise FlowRunNotFoundError(
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

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
            raise FlowRunRerunStaleRevisionError(
                expected_run_revision=expected_run_revision,
                current_run_revision=run_row.revision,
            )
        if run_row.status not in RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES:
            raise FlowRunRerunInvalidTransitionError(status=run_row.status)

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
            raise FlowRunRerunStepNotFoundError()

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
            raise FlowRunRerunMissingCurrentResultsError(
                step_ids=tuple(missing_current_result_step_ids),
            )
        root_current_result = current_results.get(rerun_step_id)
        if (
            root_current_result is None
            or root_current_result.status != FlowStepResultStatus.COMPLETED.value
        ):
            raise FlowRunRerunRootStepIncompleteError(step_ids=(rerun_step_id,))

        if (
            rerun_input_override.root_step_input is not None
            and rerun_input_override.root_step_input.step_id != rerun_step_id
        ):
            raise FlowRunRerunStepInputsInvalidError(
                step_ids=(rerun_input_override.root_step_input.step_id,)
            )

        latest_completed_attempts = await self._latest_completed_attempts_by_step_id(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_run_id=flow_run_id,
            step_ids=invalidated_step_ids,
        )
        root_attempt_no = await next_step_attempt_no(
            self.session,
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
                input_payload_json=rerun_input_override.inline_payload_json,
                root_step_input_override_requested=(
                    rerun_input_override.root_step_input is not None
                ),
                requested_by_principal_type=requested_by_principal.principal_type.value,
                requested_by_user_id=requested_by_principal.principal_user_id,
                requested_by_service_id=requested_by_principal.principal_service_id,
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
                raise FlowRunPersistenceInvariantError(
                    operation="create_rerun_operation",
                    run_id=flow_run_id,
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                )
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

        if rerun_input_override.root_step_input is not None:
            step_input_file_rows = build_step_input_file_rows(
                flow_run_id=flow_run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                attempt_no=root_attempt_no,
                projections=[
                    {
                        "step_id": rerun_step_id,
                        "step_order": rerun_step_order,
                        "file_ids": rerun_input_override.root_step_input.file_ids,
                    }
                ],
            )
            await insert_step_input_file_rows(
                session=self.session,
                rows=step_input_file_rows,
            )

        execution_input_payload = build_rerun_execution_input_envelope(
            current=run_row.input_payload_json,
            override=rerun_input_override,
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
                input_payload_json=execution_input_payload,
                output_payload_json=None,
                error_json=None,
                started_at=None,
                finished_at=None,
                cancelled_at=None,
            )
            .returning(FlowRuns)
        )
        if updated_run_row is None:
            raise FlowRunPersistenceInvariantError(
                operation="rerun_flow_run_update",
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

        return await self._rerun_command_result_from_row(
            operation_row=operation_row,
            run_row=updated_run_row,
            created=True,
        )

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
        overrides_by_operation_id = (
            await self._root_step_input_overrides_by_operation_id(rows)
        )
        return [
            self.factory.from_flow_run_rerun_operation_db(
                row,
                root_step_input_override=overrides_by_operation_id[row.id],
            )
            for row in rows
        ]

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
            raise FlowRunRerunMultipleActiveOperationsError(flow_run_id=run_id)
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
        overrides_by_operation_id = (
            await self._root_step_input_overrides_by_operation_id((operation_row,))
        )
        return FlowRunActiveRerunOperation(
            operation=self.factory.from_flow_run_rerun_operation_db(
                operation_row,
                root_step_input_override=overrides_by_operation_id[operation_row.id],
            ),
            invalidated_steps=tuple(
                self.factory.from_flow_run_rerun_invalidated_step_db(row)
                for row in invalidated_rows
            ),
        )

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
            raise FlowRunRerunAttemptLineageConflictError(
                operation_id=operation_id,
                step_id=step_id,
                new_attempt_id=new_attempt_id,
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
            raise FlowRunNotFoundError(
                run_id=operation_row.flow_run_id,
                tenant_id=operation_row.tenant_id,
                flow_id=operation_row.flow_id,
            )

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
        overrides_by_operation_id = (
            await self._root_step_input_overrides_by_operation_id((operation_row,))
        )
        return FlowRunRerunCommandResult(
            operation=self.factory.from_flow_run_rerun_operation_db(
                operation_row,
                root_step_input_override=overrides_by_operation_id[operation_row.id],
            ),
            run=self.factory.from_flow_run_db(resolved_run_row),
            invalidated_steps=tuple(
                self.factory.from_flow_run_rerun_invalidated_step_db(row)
                for row in invalidated_rows
            ),
            created=created,
        )

    async def _root_step_input_overrides_by_operation_id(
        self,
        operation_rows: Sequence[FlowRunRerunOperations],
    ) -> dict[UUID, RerunStepInputOverride | None]:
        overrides: dict[UUID, RerunStepInputOverride | None] = {
            row.id: None for row in operation_rows
        }
        requested_rows = [
            row for row in operation_rows if row.root_step_input_override_requested
        ]
        if not requested_rows:
            return overrides

        # Rows for requested=False operations are inherited runtime history copied
        # from a predecessor attempt, not evidence of an explicit override.
        requested_keys = {_rerun_step_input_key(row) for row in requested_rows}
        requested_key_tuple = tuple(requested_keys)
        file_ids_by_key: dict[_RerunStepInputKey, list[UUID]] = {
            key: [] for key in requested_keys
        }
        rows = await self.session.execute(
            sa.select(
                FlowRunStepInputFiles.flow_run_id,
                FlowRunStepInputFiles.flow_id,
                FlowRunStepInputFiles.tenant_id,
                FlowRunStepInputFiles.step_id,
                FlowRunStepInputFiles.attempt_no,
                FlowRunStepInputFiles.file_id,
            )
            .where(
                sa.tuple_(
                    FlowRunStepInputFiles.flow_run_id,
                    FlowRunStepInputFiles.flow_id,
                    FlowRunStepInputFiles.tenant_id,
                    FlowRunStepInputFiles.step_id,
                    FlowRunStepInputFiles.attempt_no,
                ).in_(requested_key_tuple)
            )
            .order_by(
                FlowRunStepInputFiles.flow_run_id.asc(),
                FlowRunStepInputFiles.flow_id.asc(),
                FlowRunStepInputFiles.tenant_id.asc(),
                FlowRunStepInputFiles.step_id.asc(),
                FlowRunStepInputFiles.attempt_no.asc(),
                FlowRunStepInputFiles.ordinal.asc(),
            )
        )
        for (
            flow_run_id,
            flow_id,
            tenant_id,
            step_id,
            attempt_no,
            file_id,
        ) in rows:
            file_ids_by_key[
                (flow_run_id, flow_id, tenant_id, step_id, attempt_no)
            ].append(file_id)

        for row in requested_rows:
            overrides[row.id] = RerunStepInputOverride(
                step_id=row.rerun_step_id,
                file_ids=tuple(file_ids_by_key[_rerun_step_input_key(row)]),
            )
        return overrides

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
        return {row.step_id: row for row in rows}

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
            if row.step_id in latest_attempts:
                continue
            latest_attempts[row.step_id] = row
        return latest_attempts
