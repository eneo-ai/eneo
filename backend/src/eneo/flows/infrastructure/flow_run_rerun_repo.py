"""Persistence owner for Flow run rerun operations and invalidated-step lineage.

Callers own the active database transaction. Accepting a rerun operation also
resets the affected run and step-result state inside that transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence, TypeAlias
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import (
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunStepInputOverride,
)
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.domain.flow_run_input_revision import (
    build_flow_run_input_revision,
    parse_flow_run_input_revision,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    start_flow_dispatch_epoch,
)
from eneo.flows.domain.rerun_exceptions import (
    FlowRunRerunAttemptLineageConflictError,
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunMultipleActiveOperationsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStaleRevisionError,
    FlowRunRerunStepInputsInvalidError,
    FlowRunRerunStepNotFoundError,
)
from eneo.flows.enums import (
    RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES,
    RERUN_OPERATION_TERMINAL_STATUS_BY_RUN_STATUS,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
)
from eneo.flows.flow_run_input_envelope import (
    RerunInputOverride,
    build_rerun_execution_input_envelope,
)
from eneo.flows.flow_run_rerun_graph import RerunInvalidatedStep
from eneo.flows.infrastructure.flow_run_step_input_file_rows import (
    build_step_input_file_rows,
    insert_step_input_file_rows,
)
from eneo.flows.infrastructure.flow_step_attempt_numbering import (
    next_step_attempt_no,
)
from eneo.flows.principal import FlowPrincipal


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


@dataclass(frozen=True, slots=True)
class FlowRunRerunEvidenceMeasurements:
    operation_row_count: int
    operation_nested_override_row_count: int
    operation_stored_json_bytes: int
    operation_logical_json_bytes: int
    invalidated_step_row_count: int
    invalidated_step_stored_json_bytes: int
    invalidated_step_logical_json_bytes: int

    @classmethod
    def empty(cls) -> "FlowRunRerunEvidenceMeasurements":
        return cls(
            operation_row_count=0,
            operation_nested_override_row_count=0,
            operation_stored_json_bytes=0,
            operation_logical_json_bytes=0,
            invalidated_step_row_count=0,
            invalidated_step_stored_json_bytes=0,
            invalidated_step_logical_json_bytes=0,
        )


@dataclass(frozen=True, slots=True)
class FlowRunRerunEvidenceRowCounts:
    operations: int
    invalidated_steps: int
    nested_overrides: int = 0


FlowRunRerunEvidenceAdmissionReason: TypeAlias = Literal["row_limit", "logical_bytes"]


@dataclass(frozen=True, slots=True)
class FlowRunRerunEvidenceAdmission:
    operations: tuple[FlowRunRerunOperation, ...]
    omission_reason: FlowRunRerunEvidenceAdmissionReason | None


def _jsonb_evidence_logical_bytes(*columns: Any) -> Any:
    return sum(
        (
            sa.func.coalesce(sa.func.octet_length(sa.cast(column, sa.Text)), 0)
            for column in columns
        ),
        start=sa.literal(0),
    )


def _scalar_evidence_logical_bytes(*columns: Any) -> Any:
    return sum(
        (
            sa.func.coalesce(
                sa.func.octet_length(sa.cast(sa.func.to_jsonb(column), sa.Text)),
                0,
            )
            for column in columns
        ),
        start=sa.literal(0),
    )


def _rerun_operation_evidence_logical_bytes() -> Any:
    return _jsonb_evidence_logical_bytes(
        FlowRunRerunOperations.input_payload_json,
        FlowRunRerunOperations.changed_input_paths,
        FlowRunRerunOperations.prior_input_payload_json,
    ) + _scalar_evidence_logical_bytes(
        FlowRunRerunOperations.reason,
        FlowRunRerunOperations.failure_message,
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


def _rerun_operation_from_row(
    row: FlowRunRerunOperations,
    *,
    root_step_input_override: RerunStepInputOverride | None,
) -> FlowRunRerunOperation:
    computed_fields = {"input_revision", "root_step_input_override"}
    payload = {
        field_name: getattr(row, field_name)
        for field_name in FlowRunRerunOperation.model_fields
        if field_name not in computed_fields
    }
    payload["input_revision"] = parse_flow_run_input_revision(
        prior_input_hash=row.prior_input_hash,
        resulting_input_hash=row.resulting_input_hash,
        changed_input_paths=row.changed_input_paths,
        prior_input_payload=row.prior_input_payload_json,
    )
    payload["root_step_input_override"] = root_step_input_override
    return FlowRunRerunOperation.model_validate(payload)


class FlowRunRerunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def measure_evidence_row_counts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        ceiling: int,
    ) -> FlowRunRerunEvidenceRowCounts:
        candidate_limit = ceiling + 1
        operation_candidates = (
            sa.select(FlowRunRerunOperations.id)
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .limit(candidate_limit)
            .subquery()
        )
        operation_count = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(operation_candidates)
            )
            or 0
        )
        override_count = 0
        if operation_count <= ceiling:
            override_candidates = (
                sa.select(FlowRunStepInputFiles.id)
                .join(
                    FlowRunRerunOperations,
                    sa.and_(
                        FlowRunRerunOperations.id.in_(
                            sa.select(operation_candidates.c.id)
                        ),
                        FlowRunRerunOperations.flow_run_id
                        == FlowRunStepInputFiles.flow_run_id,
                        FlowRunRerunOperations.flow_id == FlowRunStepInputFiles.flow_id,
                        FlowRunRerunOperations.tenant_id
                        == FlowRunStepInputFiles.tenant_id,
                        FlowRunRerunOperations.rerun_step_id
                        == FlowRunStepInputFiles.step_id,
                        FlowRunRerunOperations.root_attempt_no
                        == FlowRunStepInputFiles.attempt_no,
                        FlowRunRerunOperations.root_step_input_override_requested.is_(
                            True
                        ),
                    ),
                )
                .limit(candidate_limit)
                .subquery()
            )
            override_count = int(
                await self.session.scalar(
                    sa.select(sa.func.count()).select_from(override_candidates)
                )
                or 0
            )
        invalidated_candidates = (
            sa.select(FlowRunRerunInvalidatedSteps.id)
            .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
            .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
            .limit(candidate_limit)
            .subquery()
        )
        invalidated_count = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(invalidated_candidates)
            )
            or 0
        )
        return FlowRunRerunEvidenceRowCounts(
            operations=operation_count,
            invalidated_steps=invalidated_count,
            nested_overrides=override_count,
        )

    async def measure_evidence_sections(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> FlowRunRerunEvidenceMeasurements:
        operation_candidate_stmt = (
            sa.select(FlowRunRerunOperations.id)
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
        )
        invalidated_candidate_stmt = (
            sa.select(FlowRunRerunInvalidatedSteps.id)
            .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
            .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            operation_candidate_stmt = operation_candidate_stmt.limit(candidate_limit)
            invalidated_candidate_stmt = invalidated_candidate_stmt.limit(
                candidate_limit
            )
        operation_candidates = operation_candidate_stmt.subquery()
        invalidated_candidates = invalidated_candidate_stmt.subquery()
        operation_stored = sum(
            (
                sa.func.coalesce(sa.func.pg_column_size(column), 0)
                for column in (
                    FlowRunRerunOperations.input_payload_json,
                    FlowRunRerunOperations.changed_input_paths,
                    FlowRunRerunOperations.prior_input_payload_json,
                )
            ),
            start=sa.literal(0),
        )
        operation_logical = _rerun_operation_evidence_logical_bytes()
        operation = (
            # Paired with `_rerun_operation_from_row`: this covers its JSON
            # revision payloads and unbounded reason/failure text.
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(sa.func.sum(operation_stored), 0).label(
                        "stored_json_bytes"
                    ),
                    sa.func.coalesce(sa.func.sum(operation_logical), 0).label(
                        "logical_json_bytes"
                    ),
                )
                .where(FlowRunRerunOperations.flow_run_id == run_id)
                .where(FlowRunRerunOperations.tenant_id == tenant_id)
                .where(
                    FlowRunRerunOperations.id.in_(sa.select(operation_candidates.c.id))
                )
            )
        ).one()
        override_candidate_stmt = (
            sa.select(FlowRunStepInputFiles.id)
            .select_from(FlowRunStepInputFiles)
            .join(
                FlowRunRerunOperations,
                sa.and_(
                    FlowRunRerunOperations.flow_run_id
                    == FlowRunStepInputFiles.flow_run_id,
                    FlowRunRerunOperations.flow_id == FlowRunStepInputFiles.flow_id,
                    FlowRunRerunOperations.tenant_id == FlowRunStepInputFiles.tenant_id,
                    FlowRunRerunOperations.rerun_step_id
                    == FlowRunStepInputFiles.step_id,
                    FlowRunRerunOperations.root_attempt_no
                    == FlowRunStepInputFiles.attempt_no,
                    FlowRunRerunOperations.root_step_input_override_requested.is_(True),
                ),
            )
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .where(FlowRunRerunOperations.id.in_(sa.select(operation_candidates.c.id)))
        )
        if candidate_limit is not None:
            override_candidate_stmt = override_candidate_stmt.limit(candidate_limit)
        override_candidates = override_candidate_stmt.subquery()
        override_file = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(
                        sa.func.sum(
                            _scalar_evidence_logical_bytes(
                                FlowRunStepInputFiles.file_id
                            )
                        ),
                        0,
                    ).label("logical_json_bytes"),
                )
                .select_from(FlowRunStepInputFiles)
                .where(
                    FlowRunStepInputFiles.id.in_(sa.select(override_candidates.c.id))
                )
            )
        ).one()
        invalidated = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.func.coalesce(
                                sa.func.pg_column_size(
                                    FlowRunRerunInvalidatedSteps.dependency_sources_json
                                ),
                                0,
                            )
                        ),
                        0,
                    ).label("stored_json_bytes"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.func.coalesce(
                                sa.func.octet_length(
                                    sa.cast(
                                        FlowRunRerunInvalidatedSteps.dependency_sources_json,
                                        sa.Text,
                                    )
                                ),
                                0,
                            )
                        ),
                        0,
                    ).label("logical_json_bytes"),
                )
                .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
                .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
                .where(
                    FlowRunRerunInvalidatedSteps.id.in_(
                        sa.select(invalidated_candidates.c.id)
                    )
                )
            )
        ).one()
        return FlowRunRerunEvidenceMeasurements(
            operation_row_count=int(operation.row_count),
            operation_nested_override_row_count=int(override_file.row_count),
            operation_stored_json_bytes=int(operation.stored_json_bytes),
            operation_logical_json_bytes=int(operation.logical_json_bytes)
            + int(override_file.logical_json_bytes),
            invalidated_step_row_count=int(invalidated.row_count),
            invalidated_step_stored_json_bytes=int(invalidated.stored_json_bytes),
            invalidated_step_logical_json_bytes=int(invalidated.logical_json_bytes),
        )

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
        # Recorded before the run row is overwritten: afterwards the payload
        # this rerun replaced is gone, and the revision chain with it.
        input_revision = build_flow_run_input_revision(
            prior=run_row.input_payload_json,
            resulting=execution_input_payload,
        )
        operation_row = await self.session.scalar(
            sa.update(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.id == operation_row.id)
            .values(
                prior_input_hash=input_revision.prior_input_hash,
                resulting_input_hash=input_revision.resulting_input_hash,
                changed_input_paths=list(input_revision.changed_paths),
                prior_input_payload_json=input_revision.prior_input_payload,
            )
            .returning(FlowRunRerunOperations)
            .execution_options(populate_existing=True)
        )
        if operation_row is None:
            raise FlowRunPersistenceInvariantError(
                operation="record_rerun_input_revision",
                run_id=flow_run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == flow_run_id)
            .where(FlowStepResults.flow_id == flow_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.step_id.in_(invalidated_step_ids))
            .values(**_RERUN_STEP_RESULT_RESET_VALUES)
        )
        now_utc = datetime.now(timezone.utc)
        updated_run_row = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(
                status=FlowRunStatus.QUEUED.value,
                revision=run_row.revision + 1,
                **start_flow_dispatch_epoch(now_utc),
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
            "status": RERUN_OPERATION_TERMINAL_STATUS_BY_RUN_STATUS[
                target_status
            ].value,
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
        limit: int | None = None,
        logical_byte_budget: int | None = None,
    ) -> list[FlowRunRerunOperation]:
        if limit is not None and logical_byte_budget is not None:
            admission = await self.list_rerun_operations_for_evidence_view(
                run_id=run_id,
                tenant_id=tenant_id,
                limit=limit,
                logical_byte_budget=logical_byte_budget,
            )
            return list(admission.operations)
        stmt = (
            sa.select(FlowRunRerunOperations)
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .order_by(
                FlowRunRerunOperations.accepted_run_revision.asc(),
                FlowRunRerunOperations.created_at.asc(),
                FlowRunRerunOperations.id.asc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        overrides_by_operation_id = (
            await self._root_step_input_overrides_by_operation_id(rows)
        )
        return [
            _rerun_operation_from_row(
                row,
                root_step_input_override=overrides_by_operation_id[row.id],
            )
            for row in rows
        ]

    async def list_rerun_operations_for_evidence_view(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int,
        logical_byte_budget: int,
    ) -> FlowRunRerunEvidenceAdmission:
        override_candidate_stmt = (
            sa.select(FlowRunStepInputFiles.file_id.label("file_id"))
            .where(
                FlowRunStepInputFiles.flow_run_id == FlowRunRerunOperations.flow_run_id,
                FlowRunStepInputFiles.tenant_id == FlowRunRerunOperations.tenant_id,
                FlowRunStepInputFiles.step_id == FlowRunRerunOperations.rerun_step_id,
                FlowRunStepInputFiles.attempt_no
                == FlowRunRerunOperations.root_attempt_no,
                FlowRunRerunOperations.root_step_input_override_requested.is_(True),
            )
            .limit(limit + 1)
            .correlate(FlowRunRerunOperations)
        )
        override_candidates = override_candidate_stmt.subquery()
        override_logical = (
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(
                        _scalar_evidence_logical_bytes(override_candidates.c.file_id)
                    ),
                    0,
                )
            )
            .correlate(FlowRunRerunOperations)
            .scalar_subquery()
        )
        override_count = (
            sa.select(sa.func.count())
            .select_from(override_candidates)
            .correlate(FlowRunRerunOperations)
            .scalar_subquery()
        )
        candidates = (
            sa.select(
                FlowRunRerunOperations.id.label("row_id"),
                FlowRunRerunOperations.accepted_run_revision.label("revision"),
                FlowRunRerunOperations.created_at.label("created_at"),
                (_rerun_operation_evidence_logical_bytes() + override_logical).label(
                    "logical_bytes"
                ),
                override_count.label("override_count"),
            )
            .where(FlowRunRerunOperations.flow_run_id == run_id)
            .where(FlowRunRerunOperations.tenant_id == tenant_id)
            .order_by(
                FlowRunRerunOperations.accepted_run_revision.asc(),
                FlowRunRerunOperations.created_at.asc(),
                FlowRunRerunOperations.id.asc(),
            )
            .limit(limit + 1)
            .subquery()
        )
        order = (
            candidates.c.revision,
            candidates.c.created_at,
            candidates.c.row_id,
        )
        ranked = sa.select(
            candidates.c.row_id,
            sa.func.row_number().over(order_by=order).label("row_rank"),
            sa.func.sum(candidates.c.logical_bytes)
            .over(order_by=order)
            .label("cumulative_logical"),
            sa.func.sum(candidates.c.override_count)
            .over(order_by=order)
            .label("cumulative_override_count"),
        ).subquery()
        admitted_row_ids = sa.select(ranked.c.row_id).where(
            ranked.c.row_rank <= limit,
            ranked.c.cumulative_logical <= logical_byte_budget,
            ranked.c.cumulative_override_count <= limit,
        )
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunRerunOperations)
                    .where(FlowRunRerunOperations.flow_run_id == run_id)
                    .where(FlowRunRerunOperations.tenant_id == tenant_id)
                    .where(FlowRunRerunOperations.id.in_(admitted_row_ids))
                    .order_by(
                        FlowRunRerunOperations.accepted_run_revision.asc(),
                        FlowRunRerunOperations.created_at.asc(),
                        FlowRunRerunOperations.id.asc(),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        rejection_reason = await self.session.scalar(
            sa.select(
                sa.case(
                    (
                        ranked.c.cumulative_override_count > limit,
                        sa.literal("row_limit"),
                    ),
                    (ranked.c.row_rank > limit, sa.literal("row_limit")),
                    (
                        ranked.c.cumulative_logical > logical_byte_budget,
                        sa.literal("logical_bytes"),
                    ),
                )
            )
            .where(
                sa.or_(
                    ranked.c.row_rank > limit,
                    ranked.c.cumulative_logical > logical_byte_budget,
                    ranked.c.cumulative_override_count > limit,
                )
            )
            .order_by(ranked.c.row_rank)
            .limit(1)
        )
        omission_reason: FlowRunRerunEvidenceAdmissionReason | None
        if rejection_reason == "row_limit":
            omission_reason = "row_limit"
        elif rejection_reason == "logical_bytes":
            omission_reason = "logical_bytes"
        else:
            omission_reason = None
        overrides_by_operation_id = (
            await self._root_step_input_overrides_by_operation_id(rows)
        )
        return FlowRunRerunEvidenceAdmission(
            operations=tuple(
                _rerun_operation_from_row(
                    row,
                    root_step_input_override=overrides_by_operation_id[row.id],
                )
                for row in rows
            ),
            omission_reason=omission_reason,
        )

    async def list_rerun_invalidated_steps_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
        operation_ids: Sequence[UUID] | None = None,
        logical_byte_budget: int | None = None,
    ) -> list[FlowRunRerunInvalidatedStep]:
        if operation_ids is not None and not operation_ids:
            return []
        stmt = (
            sa.select(FlowRunRerunInvalidatedSteps)
            .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
            .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
            .order_by(
                FlowRunRerunInvalidatedSteps.operation_id.asc(),
                FlowRunRerunInvalidatedSteps.invalidation_order.asc(),
                FlowRunRerunInvalidatedSteps.id.asc(),
            )
        )
        if operation_ids is not None:
            stmt = stmt.where(
                FlowRunRerunInvalidatedSteps.operation_id.in_(operation_ids)
            )
        if limit is not None and logical_byte_budget is not None:
            candidate_stmt = (
                sa.select(
                    FlowRunRerunInvalidatedSteps.id.label("row_id"),
                    FlowRunRerunInvalidatedSteps.operation_id.label("operation_id"),
                    FlowRunRerunInvalidatedSteps.invalidation_order.label(
                        "invalidation_order"
                    ),
                    _jsonb_evidence_logical_bytes(
                        FlowRunRerunInvalidatedSteps.dependency_sources_json
                    ).label("logical_bytes"),
                )
                .where(FlowRunRerunInvalidatedSteps.flow_run_id == run_id)
                .where(FlowRunRerunInvalidatedSteps.tenant_id == tenant_id)
            )
            if operation_ids is not None:
                candidate_stmt = candidate_stmt.where(
                    FlowRunRerunInvalidatedSteps.operation_id.in_(operation_ids)
                )
            candidates = (
                candidate_stmt.order_by(
                    FlowRunRerunInvalidatedSteps.operation_id.asc(),
                    FlowRunRerunInvalidatedSteps.invalidation_order.asc(),
                    FlowRunRerunInvalidatedSteps.id.asc(),
                )
                .limit(limit + 1)
                .subquery()
            )
            order = (
                candidates.c.operation_id,
                candidates.c.invalidation_order,
                candidates.c.row_id,
            )
            ranked = sa.select(
                candidates.c.row_id,
                sa.func.row_number().over(order_by=order).label("row_rank"),
                sa.func.sum(candidates.c.logical_bytes)
                .over(order_by=order)
                .label("cumulative_logical"),
            ).subquery()
            stmt = stmt.where(
                FlowRunRerunInvalidatedSteps.id.in_(
                    sa.select(ranked.c.row_id).where(
                        ranked.c.row_rank <= limit,
                        ranked.c.cumulative_logical <= logical_byte_budget,
                    )
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [FlowRunRerunInvalidatedStep.model_validate(row) for row in rows]

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
            operation=_rerun_operation_from_row(
                operation_row,
                root_step_input_override=overrides_by_operation_id[operation_row.id],
            ),
            invalidated_steps=tuple(
                FlowRunRerunInvalidatedStep.model_validate(row)
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
            operation=_rerun_operation_from_row(
                operation_row,
                root_step_input_override=overrides_by_operation_id[operation_row.id],
            ),
            run=FlowRun.model_validate(resolved_run_row),
            invalidated_steps=tuple(
                FlowRunRerunInvalidatedStep.model_validate(row)
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
