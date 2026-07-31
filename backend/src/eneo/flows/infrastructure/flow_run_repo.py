from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence, TypedDict, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, aliased

from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_models import FileContentVariant, FileMetadata, FileType
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    FileRepository,
    project_file_info,
    select_primary_file_reference,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunNotFoundError,
    FlowRunPersistenceInvariantError,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    flow_dispatch_retry_delay_seconds,
    start_flow_dispatch_epoch,
)
from eneo.flows.domain.flow_step_attempt_input import (
    FlowStepAttemptInput,
    merge_flow_step_attempt_input,
    parse_flow_step_attempt_input,
)
from eneo.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES,
    CANCELLABLE_FLOW_RUN_STATUSES,
    OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES,
    TERMINAL_FLOW_RUN_STATUSES,
)
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunError,
    dump_flow_run_dispatch_error,
    dump_flow_run_error,
)
from eneo.flows.flow_run_input_envelope import (
    FlowRunInputEnvelopePatch,
)
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdges,
    FlowResolvedInputEdgesConflictError,
    FlowResolvedInputEdgesParseResult,
    FlowResolvedInputEdgesUnavailableError,
    parse_resolved_input_edges,
    require_attempt_runtime_evidence_not_purged,
    resolve_attempt_terminalization_evidence,
)
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFileProjection
from eneo.flows.flow_run_step_result_file import (
    FlowRunStepResultFile,
    FlowRunStepResultFileAvailability,
    FlowRunStepResultFileSource,
    FlowStepResultFileReference,
)
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_staleness import (
    stale_running_flow_run_predicate,
)
from eneo.flows.infrastructure.flow_run_step_input_file_rows import (
    build_step_input_file_rows,
    insert_step_input_file_rows,
)
from eneo.flows.infrastructure.flow_step_attempt_numbering import (
    next_step_attempt_no,
)
from eneo.flows.principal import FlowPrincipal
from eneo.object_content.content import ContentState


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int


def _recorded_passage_byte_expressions() -> tuple[Any, Any]:
    """The one SQL reading of the persisted passage-byte aggregate.

    Returns (bytes, is_corrupt). Absent RAG measures zero — a run without
    retrieval holds no passages. A malformed or negative value is corruption:
    it must never measure as zero, because zero would let unreadable evidence
    slip under an exact size budget, and it must never reach a bare cast,
    because that fails the whole statement. Both readers share this expression
    so the two cannot drift apart again.
    """
    raw = sa.func.jsonb_extract_path_text(
        FlowStepAttempts.provenance_json,
        "rag",
        "recorded_passage_bytes",
    )
    is_numeric = raw.op("~")(sa.literal(r"^[0-9]{1,15}$"))
    passage_bytes = sa.case(
        (is_numeric, sa.cast(raw, sa.BigInteger)),
        else_=sa.literal(0, sa.BigInteger),
    )
    is_corrupt = sa.and_(raw.is_not(None), sa.not_(is_numeric))
    return passage_bytes, is_corrupt


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


def _step_result_evidence_logical_bytes() -> Any:
    # Paired with `FlowStepResult.model_validate`: every unbounded value in the
    # emitted projection participates in both preflight and view admission.
    return _jsonb_evidence_logical_bytes(
        FlowStepResults.input_payload_json,
        FlowStepResults.output_payload_json,
        FlowStepResults.model_parameters_json,
    ) + _scalar_evidence_logical_bytes(
        FlowStepResults.effective_prompt,
        FlowStepResults.error_code,
        FlowStepResults.error_message,
        FlowStepResults.flow_step_execution_hash,
    )


def _file_evidence_logical_bytes() -> Any:
    return _scalar_evidence_logical_bytes(Files.name, Files.mimetype)


def _attempt_evidence_logical_bytes() -> Any:
    # Paired with `_dump_attempt_record`, including every emitted unbounded text
    # scalar and exact resolved-input lineage so escaping expansion cannot
    # bypass the budget.
    return _jsonb_evidence_logical_bytes(
        FlowStepAttempts.provenance_json,
        FlowStepAttempts.input_payload_json,
        FlowStepAttempts.output_payload_json,
        FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb,
    ) + _scalar_evidence_logical_bytes(
        FlowStepAttempts.celery_task_id,
        FlowStepAttempts.error_code,
        FlowStepAttempts.error_message,
        FlowStepAttempts.requested_model,
        FlowStepAttempts.response_model,
        FlowStepAttempts.provider,
        FlowStepAttempts.finish_reason,
        FlowStepAttempts.provider_response_id,
        FlowStepAttempts.flow_step_execution_hash,
    )


@dataclass(frozen=True, slots=True)
class StepAttemptPage:
    """One snapshot's admitted attempts and the counts that qualify them.

    `current_total` and `current_admitted` exist so a caller can say when a
    step's current attempt was excluded by a budget — silently missing current
    evidence would read as the step never having retrieved anything. When
    `count_truncated` is true, every count and
    `current_step_orders_not_loaded` is conservative evidence from the bounded
    candidate relation: counts are lower bounds and the step orders are a known
    subset, not an exhaustive list.
    """

    attempts: list[FlowStepAttempt]
    total_count: int
    current_total: int
    current_admitted: int
    count_truncated: bool
    current_step_orders_not_loaded: tuple[int, ...] = ()
    corrupt_passage_aggregates: int = 0


@dataclass(frozen=True, slots=True)
class StepAttemptEvidenceSize:
    """How much attempt evidence a run holds, measured without loading it.

    The two byte measures answer different questions and must not be
    conflated. `recorded_passage_bytes` sums the exact aggregate each RAG
    payload stores about its own passages — the right measure for a
    passage-size limit. `stored_provenance_bytes` is the stored size of the
    whole provenance object, RAG or not — a materialization-cost measure,
    where TOAST compression makes it a floor, never a passage count.
    """

    attempt_count: int
    stored_provenance_bytes: int
    recorded_passage_bytes: int
    stored_json_bytes: int = 0
    logical_json_bytes: int = 0
    corrupt_passage_aggregates: int = 0


@dataclass(frozen=True, slots=True)
class FlowRunEvidenceMeasurements:
    run_row_count: int
    run_stored_json_bytes: int
    run_logical_json_bytes: int
    step_result_row_count: int
    step_result_stored_json_bytes: int
    step_result_logical_json_bytes: int
    result_file_row_count: int
    result_file_logical_json_bytes: int
    runtime_input_file_row_count: int
    runtime_input_file_logical_json_bytes: int

    @classmethod
    def empty(cls) -> "FlowRunEvidenceMeasurements":
        return cls(
            run_row_count=0,
            run_stored_json_bytes=0,
            run_logical_json_bytes=0,
            step_result_row_count=0,
            step_result_stored_json_bytes=0,
            step_result_logical_json_bytes=0,
            result_file_row_count=0,
            result_file_logical_json_bytes=0,
            runtime_input_file_row_count=0,
            runtime_input_file_logical_json_bytes=0,
        )


@dataclass(frozen=True, slots=True)
class FlowRunEvidenceRowCounts:
    step_results: int
    step_attempts: int
    result_files: int
    runtime_input_files: int


def _bounded_step_result_evidence_count_statement(
    *, run_id: UUID, tenant_id: UUID, ceiling: int
) -> sa.Select[tuple[int]]:
    candidates = (
        sa.select(FlowStepResults.id)
        .where(FlowStepResults.flow_run_id == run_id)
        .where(FlowStepResults.tenant_id == tenant_id)
        .limit(ceiling + 1)
        .subquery()
    )
    return sa.select(sa.func.count()).select_from(candidates)


def _bounded_step_result_evidence_size_statement(
    *, run_id: UUID, tenant_id: UUID, candidate_limit: int
) -> sa.Select[Any]:
    stored = sum(
        (
            sa.func.coalesce(sa.func.pg_column_size(column), 0)
            for column in (
                FlowStepResults.input_payload_json,
                FlowStepResults.output_payload_json,
                FlowStepResults.model_parameters_json,
            )
        ),
        start=sa.literal(0),
    )
    candidates = (
        sa.select(
            stored.label("stored_json_bytes"),
            _step_result_evidence_logical_bytes().label("logical_json_bytes"),
        )
        .where(FlowStepResults.flow_run_id == run_id)
        .where(FlowStepResults.tenant_id == tenant_id)
        .limit(candidate_limit)
        .subquery()
    )
    return sa.select(
        sa.func.count().label("row_count"),
        sa.func.coalesce(sa.func.sum(candidates.c.stored_json_bytes), 0).label(
            "stored_json_bytes"
        ),
        sa.func.coalesce(sa.func.sum(candidates.c.logical_json_bytes), 0).label(
            "logical_json_bytes"
        ),
    ).select_from(candidates)


@dataclass(frozen=True, slots=True)
class FlowRunDispatchRedriveGenerationConflict:
    current_dispatch_exhausted_at: datetime | None


def _current_step_attempt_pairs_by_result_id(
    step_results: Sequence[FlowStepResult],
) -> tuple[dict[tuple[UUID, int], UUID], list[tuple[UUID, int]]]:
    step_result_id_by_step_attempt: dict[tuple[UUID, int], UUID] = {}
    current_attempt_pairs: list[tuple[UUID, int]] = []
    for result in step_results:
        if result.id is None or result.current_attempt_no is None:
            continue
        pair = (result.step_id, result.current_attempt_no)
        step_result_id_by_step_attempt[pair] = result.id
        current_attempt_pairs.append(pair)
    return step_result_id_by_step_attempt, current_attempt_pairs


_CANCELLABLE_RUN_STATUSES = tuple(
    status.value for status in CANCELLABLE_FLOW_RUN_STATUSES
)


class FlowRunRepository:
    """Tenant-scoped repository for flow run lifecycle and run evidence."""

    _ACTIVE_STATUSES = tuple(status.value for status in ACTIVE_FLOW_RUN_STATUSES)

    def __init__(
        self,
        session: AsyncSession,
        audit_outbox_repo: FlowRunAuditOutboxRepository | None = None,
    ):
        self.session = session
        self.audit_outbox_repo = audit_outbox_repo or FlowRunAuditOutboxRepository(
            session=session
        )

    async def create(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        principal_type: str = "user",
        principal_user_id: UUID | None = None,
        principal_service_id: UUID | None = None,
        created_by_api_key_id: UUID | None = None,
        runtime_service_permission: ApiKeyPermission | None = None,
        tenant_id: UUID,
        input_payload_json: dict[str, Any] | None,
        preseed_steps: Sequence["PreseedStep"],
        step_input_files: Sequence[FlowRunStepInputFileProjection] | None = None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> FlowRun:
        now_utc = datetime.now(timezone.utc)
        principal = FlowPrincipal(
            principal_type=PrincipalType(principal_type),
            principal_user_id=principal_user_id,
            principal_service_id=principal_service_id,
            actor_api_key_id=created_by_api_key_id,
        )
        run_row = await self.session.scalar(
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                principal_type=principal.principal_type.value,
                principal_user_id=principal.principal_user_id,
                principal_service_id=principal.principal_service_id,
                created_by_api_key_id=principal.actor_api_key_id,
                runtime_service_permission=(
                    runtime_service_permission.value
                    if runtime_service_permission is not None
                    else None
                ),
                tenant_id=tenant_id,
                trace_id=uuid4(),
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                status=FlowRunStatus.QUEUED.value,
                **start_flow_dispatch_epoch(now_utc),
                input_payload_json=input_payload_json,
            )
            .returning(FlowRuns)
        )
        if run_row is None:
            raise FlowRunPersistenceInvariantError(
                operation="create_flow_run",
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

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

        step_input_file_rows = build_step_input_file_rows(
            flow_run_id=run_row.id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            attempt_no=1,
            projections=step_input_files,
        )
        await insert_step_input_file_rows(
            session=self.session,
            rows=step_input_file_rows,
        )

        return FlowRun.model_validate(run_row)

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
            raise FlowRunNotFoundError(
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        return FlowRun.model_validate(run_row)

    async def get_idempotent_run(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        idempotency_key: str,
        principal: FlowPrincipal,
    ) -> tuple[FlowRun, str | None] | None:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.idempotency_key == idempotency_key)
            .where(FlowRuns.principal_type == principal.principal_type.value)
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal.principal_user_id)
        if principal.principal_service_id is not None:
            stmt = stmt.where(
                FlowRuns.principal_service_id == principal.principal_service_id
            )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return FlowRun.model_validate(row), row.request_fingerprint

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
        statuses: Sequence[FlowRunStatus] | None = None,
        principal_user_id: UUID | None = None,
        principal_service_id: UUID | None = None,
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
        if statuses:
            stmt = stmt.where(
                FlowRuns.status.in_(tuple(status.value for status in statuses))
            )
        if principal_user_id is not None:
            stmt = stmt.where(FlowRuns.principal_user_id == principal_user_id)
        if principal_service_id is not None:
            stmt = stmt.where(FlowRuns.principal_service_id == principal_service_id)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [FlowRun.model_validate(row) for row in rows]

    async def list_dispatchable_queued_runs(
        self,
        *,
        tenant_id: UUID,
        due_at: datetime,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.dispatch_next_attempt_at <= due_at)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
            .order_by(
                FlowRuns.dispatch_next_attempt_at.asc(),
                FlowRuns.id.asc(),
            )
            .limit(limit)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        if run_id is not None:
            stmt = stmt.where(FlowRuns.id == run_id)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [FlowRun.model_validate(row) for row in rows]

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
            .where(stale_running_flow_run_predicate(stale_before=stale_before))
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [FlowRun.model_validate(row) for row in rows]

    async def claim_queued_run_for_dispatch(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        now: datetime,
        flow_id: UUID | None = None,
    ) -> FlowRun | None:
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(FlowRuns.dispatch_next_attempt_at <= now)
            .where(FlowRuns.dispatch_attempt_count < FLOW_DISPATCH_MAX_ATTEMPTS)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        claimed = await self.session.scalar(
            stmt.values(
                dispatch_attempt_count=FlowRuns.dispatch_attempt_count + 1,
                dispatch_last_attempt_at=now,
                dispatch_last_error=None,
                dispatched_at=sa.case(
                    (
                        sa.and_(
                            FlowRuns.dispatch_attempt_count > 0,
                            FlowRuns.dispatch_last_error.is_(None),
                            FlowRuns.dispatched_at.is_(None),
                        ),
                        now,
                    ),
                    else_=FlowRuns.dispatched_at,
                ),
                dispatch_next_attempt_at=now
                + timedelta(seconds=FLOW_QUEUED_REDISPATCH_AFTER_SECONDS),
                updated_at=FlowRuns.updated_at,
            ).returning(FlowRuns)
        )
        if claimed is None:
            return None
        return FlowRun.model_validate(claimed)

    async def mark_dispatch_exhausted_if_due(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        now: datetime,
    ) -> FlowRun | None:
        exhausted = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(FlowRuns.dispatch_next_attempt_at <= now)
            .where(FlowRuns.dispatch_attempt_count >= FLOW_DISPATCH_MAX_ATTEMPTS)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
            .values(
                dispatch_next_attempt_at=None,
                dispatch_exhausted_at=now,
                updated_at=FlowRuns.updated_at,
            )
            .returning(FlowRuns)
        )
        if exhausted is None:
            return None
        return FlowRun.model_validate(exhausted)

    async def rearm_exhausted_accepted_dispatch_for_redrive(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        expected_dispatch_exhausted_at: datetime | None,
        now: datetime,
    ) -> FlowRun | FlowRunDispatchRedriveGenerationConflict | None:
        """Start a fresh bounded epoch for accepted or outcome-unknown exhaustion."""

        row = await self.session.scalar(
            sa.select(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.revision == expected_revision)
            .with_for_update()
        )
        if row is None:
            return None
        if row.status != FlowRunStatus.QUEUED.value:
            return None
        current_dispatch_exhausted_at = row.dispatch_exhausted_at
        if (
            expected_dispatch_exhausted_at is not None
            and expected_dispatch_exhausted_at != current_dispatch_exhausted_at
        ):
            return FlowRunDispatchRedriveGenerationConflict(
                current_dispatch_exhausted_at=current_dispatch_exhausted_at
            )
        accepted_or_outcome_unknown_exhaustion = (
            current_dispatch_exhausted_at is not None
            and (row.dispatched_at is not None or row.dispatch_last_error is None)
        )
        if not accepted_or_outcome_unknown_exhaustion:
            return None
        assert current_dispatch_exhausted_at is not None
        if expected_dispatch_exhausted_at != current_dispatch_exhausted_at:
            return FlowRunDispatchRedriveGenerationConflict(
                current_dispatch_exhausted_at=current_dispatch_exhausted_at
            )

        rearmed = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(
                sa.or_(
                    FlowRuns.dispatched_at.is_not(None),
                    FlowRuns.dispatch_last_error.is_(None),
                )
            )
            .where(FlowRuns.dispatch_exhausted_at == expected_dispatch_exhausted_at)
            .values(
                **start_flow_dispatch_epoch(now),
                updated_at=FlowRuns.updated_at,
            )
            .returning(FlowRuns)
        )
        if rearmed is None:
            return None
        return FlowRun.model_validate(rearmed)

    async def record_dispatch_accepted(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        expected_attempt_count: int,
        now: datetime,
    ) -> FlowRun | None:
        accepted = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(FlowRuns.dispatch_attempt_count == expected_attempt_count)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
            .values(
                dispatched_at=sa.func.coalesce(FlowRuns.dispatched_at, now),
                dispatch_next_attempt_at=now
                + timedelta(
                    seconds=flow_dispatch_retry_delay_seconds(
                        attempt_no=expected_attempt_count
                    )
                ),
                updated_at=FlowRuns.updated_at,
            )
            .returning(FlowRuns)
        )
        if accepted is None:
            return None
        return FlowRun.model_validate(accepted)

    async def record_dispatch_outcome_unknown(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        expected_attempt_count: int,
        now: datetime,
    ) -> FlowRun | None:
        """Preserve a transport-ambiguous attempt without inventing a rejection."""

        values: dict[str, Any] = {
            "dispatch_last_error": None,
            "dispatched_at": sa.func.coalesce(FlowRuns.dispatched_at, now),
            "updated_at": FlowRuns.updated_at,
        }
        if expected_attempt_count >= FLOW_DISPATCH_MAX_ATTEMPTS:
            values.update(
                dispatch_next_attempt_at=None,
                dispatch_exhausted_at=now,
            )
        run = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(FlowRuns.dispatch_attempt_count == expected_attempt_count)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
            .values(**values)
            .returning(FlowRuns)
        )
        if run is None:
            return None
        return FlowRun.model_validate(run)

    async def record_dispatch_failure(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
        expected_attempt_count: int,
        error: FlowRunDispatchError,
        now: datetime,
    ) -> FlowRun | None:
        exhausted = (
            not error.retryable or expected_attempt_count >= FLOW_DISPATCH_MAX_ATTEMPTS
        )
        next_attempt_at = None
        if not exhausted:
            next_attempt_at = now + timedelta(
                seconds=flow_dispatch_retry_delay_seconds(
                    attempt_no=expected_attempt_count
                )
            )
        failed = await self.session.scalar(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .where(FlowRuns.dispatch_attempt_count == expected_attempt_count)
            .where(FlowRuns.dispatch_exhausted_at.is_(None))
            .values(
                dispatch_last_error=dump_flow_run_dispatch_error(error),
                dispatch_next_attempt_at=next_attempt_at,
                dispatch_exhausted_at=now if exhausted else None,
                updated_at=FlowRuns.updated_at,
            )
            .returning(FlowRuns)
        )
        if failed is None:
            return None
        return FlowRun.model_validate(failed)

    async def terminalize_run_status(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
        stale_before: datetime | None = None,
    ) -> FlowRun | None:
        if target_status not in TERMINAL_FLOW_RUN_STATUSES:
            raise ValueError("target_status must be terminal")

        values: dict[str, Any] = {
            "status": target_status.value,
            "error_json": dump_flow_run_error(error),
            "output_payload_json": output_payload_json,
            "finished_at": datetime.now(timezone.utc),
        }
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at

        source_statuses = (
            _CANCELLABLE_RUN_STATUSES
            if target_status == FlowRunStatus.CANCELLED
            else self._ACTIVE_STATUSES
        )
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(source_statuses))
        )
        if stale_before is not None:
            stmt = stmt.where(FlowRuns.updated_at <= stale_before)
        run_row = await self.session.scalar(stmt.values(**values).returning(FlowRuns))
        if run_row is None:
            return None
        return FlowRun.model_validate(run_row)

    async def count_active_step_results(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES))
        )
        return int(count or 0)

    async def count_open_step_attempts(self, *, run_id: UUID, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
        )
        return int(count or 0)

    async def close_active_step_results_for_terminal_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowStepResultStatus,
        error_code: str | None,
        error_message: str | None = None,
    ) -> int:
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(FlowStepResults.status.in_(ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES))
            .values(
                status=target_status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
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
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
            .values(
                status=target_status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def update_input_payload(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        input_payload_patch: FlowRunInputEnvelopePatch,
    ) -> FlowPersistedJsonObject:
        current_payload = await self.session.scalar(
            sa.select(FlowRuns.input_payload_json)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        updated_payload = input_payload_patch.apply_to(current_payload)
        await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .values(input_payload_json=updated_payload)
        )
        return updated_payload

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
        logical_byte_budget: int | None = None,
    ) -> list[FlowStepResult]:
        stmt = (
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .order_by(FlowStepResults.step_order.asc())
        )
        if limit is not None and logical_byte_budget is not None:
            candidates = (
                sa.select(
                    FlowStepResults.id.label("row_id"),
                    FlowStepResults.step_order.label("step_order"),
                    _step_result_evidence_logical_bytes().label("logical_bytes"),
                )
                .where(FlowStepResults.flow_run_id == run_id)
                .where(FlowStepResults.tenant_id == tenant_id)
                .order_by(FlowStepResults.step_order.asc(), FlowStepResults.id.asc())
                .limit(limit + 1)
                .subquery()
            )
            ranked = sa.select(
                candidates.c.row_id,
                sa.func.row_number()
                .over(order_by=(candidates.c.step_order, candidates.c.row_id))
                .label("row_rank"),
                sa.func.sum(candidates.c.logical_bytes)
                .over(order_by=(candidates.c.step_order, candidates.c.row_id))
                .label("cumulative_logical"),
            ).subquery()
            stmt = stmt.where(
                FlowStepResults.id.in_(
                    sa.select(ranked.c.row_id).where(
                        ranked.c.row_rank <= limit,
                        ranked.c.cumulative_logical <= logical_byte_budget,
                    )
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [FlowStepResult.model_validate(row) for row in rows]

    async def measure_evidence_row_counts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        ceiling: int,
    ) -> FlowRunEvidenceRowCounts:
        """Read at most ceiling+1 identities for each emitted fan-out."""
        candidate_limit = ceiling + 1
        step_attempts = (
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .limit(candidate_limit)
            .subquery()
        )
        result_files = (
            sa.select(FlowRunStepResultFiles.id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .limit(candidate_limit)
            .subquery()
        )
        runtime_input_files = (
            sa.select(FlowRunStepInputFiles.id)
            .join(
                FlowStepResults,
                sa.and_(
                    FlowStepResults.flow_run_id == FlowRunStepInputFiles.flow_run_id,
                    FlowStepResults.tenant_id == FlowRunStepInputFiles.tenant_id,
                    FlowStepResults.step_id == FlowRunStepInputFiles.step_id,
                    FlowStepResults.current_attempt_no
                    == FlowRunStepInputFiles.attempt_no,
                ),
            )
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .where(FlowRunStepInputFiles.tenant_id == tenant_id)
            .limit(candidate_limit)
            .subquery()
        )
        step_result_count = int(
            await self.session.scalar(
                _bounded_step_result_evidence_count_statement(
                    run_id=run_id, tenant_id=tenant_id, ceiling=ceiling
                )
            )
            or 0
        )
        counts: list[int] = []
        for candidates in (
            step_attempts,
            result_files,
            runtime_input_files,
        ):
            counts.append(
                int(
                    await self.session.scalar(
                        sa.select(sa.func.count()).select_from(candidates)
                    )
                    or 0
                )
            )
        return FlowRunEvidenceRowCounts(step_result_count, *counts)

    async def measure_evidence_sections(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> FlowRunEvidenceMeasurements:
        run_stored = sum(
            (
                sa.func.coalesce(sa.func.pg_column_size(column), 0)
                for column in (
                    FlowRuns.dispatch_last_error,
                    FlowRuns.input_payload_json,
                    FlowRuns.output_payload_json,
                    FlowRuns.error_json,
                )
            ),
            start=sa.literal(0),
        )
        run_logical = sum(
            (
                sa.func.coalesce(sa.func.octet_length(sa.cast(column, sa.Text)), 0)
                for column in (
                    FlowRuns.dispatch_last_error,
                    FlowRuns.input_payload_json,
                    FlowRuns.output_payload_json,
                    FlowRuns.error_json,
                )
            ),
            start=sa.literal(0),
        )
        run_measurement = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(sa.func.sum(run_stored), 0).label(
                        "stored_json_bytes"
                    ),
                    sa.func.coalesce(sa.func.sum(run_logical), 0).label(
                        "logical_json_bytes"
                    ),
                )
                .where(FlowRuns.id == run_id)
                .where(FlowRuns.tenant_id == tenant_id)
            )
        ).one()

        result_measurement = (
            await self.session.execute(
                _bounded_step_result_evidence_size_statement(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    candidate_limit=candidate_limit or 2_147_483_647,
                )
            )
        ).one()

        # Paired with `_result_file_from_rows`: file names and MIME types are
        # the only variable-width values that projection adds to the link row.
        result_file_stmt = (
            sa.select(FlowRunStepResultFiles.id)
            .where(FlowRunStepResultFiles.flow_run_id == run_id)
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            result_file_stmt = result_file_stmt.limit(candidate_limit)
        result_file_candidates = result_file_stmt.subquery()
        result_file_measurement = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(
                        sa.func.sum(_file_evidence_logical_bytes()),
                        0,
                    ).label("logical_json_bytes"),
                )
                .select_from(FlowRunStepResultFiles)
                .join(Files, Files.id == FlowRunStepResultFiles.file_id)
                .where(FlowRunStepResultFiles.flow_run_id == run_id)
                .where(FlowRunStepResultFiles.tenant_id == tenant_id)
                .where(
                    FlowRunStepResultFiles.id.in_(
                        sa.select(result_file_candidates.c.id)
                    )
                )
            )
        ).one()
        # Paired with `list_current_step_input_file_metadata_by_step_result_id`:
        # runtime-file metadata emits the same unbounded file text fields.
        runtime_input_stmt = (
            sa.select(FlowRunStepInputFiles.id)
            .join(
                FlowStepResults,
                sa.and_(
                    FlowStepResults.flow_run_id == FlowRunStepInputFiles.flow_run_id,
                    FlowStepResults.tenant_id == FlowRunStepInputFiles.tenant_id,
                    FlowStepResults.step_id == FlowRunStepInputFiles.step_id,
                    FlowStepResults.current_attempt_no
                    == FlowRunStepInputFiles.attempt_no,
                ),
            )
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .where(FlowRunStepInputFiles.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            runtime_input_stmt = runtime_input_stmt.limit(candidate_limit)
        runtime_input_candidates = runtime_input_stmt.subquery()
        runtime_input_file_measurement = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(
                        sa.func.sum(_file_evidence_logical_bytes()),
                        0,
                    ).label("logical_json_bytes"),
                )
                .select_from(FlowRunStepInputFiles)
                .join(Files, Files.id == FlowRunStepInputFiles.file_id)
                .join(
                    FlowStepResults,
                    sa.and_(
                        FlowStepResults.flow_run_id
                        == FlowRunStepInputFiles.flow_run_id,
                        FlowStepResults.tenant_id == FlowRunStepInputFiles.tenant_id,
                        FlowStepResults.step_id == FlowRunStepInputFiles.step_id,
                        FlowStepResults.current_attempt_no
                        == FlowRunStepInputFiles.attempt_no,
                    ),
                )
                .where(FlowRunStepInputFiles.flow_run_id == run_id)
                .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                .where(
                    FlowRunStepInputFiles.id.in_(
                        sa.select(runtime_input_candidates.c.id)
                    )
                )
            )
        ).one()
        return FlowRunEvidenceMeasurements(
            run_row_count=int(run_measurement.row_count),
            run_stored_json_bytes=int(run_measurement.stored_json_bytes),
            run_logical_json_bytes=int(run_measurement.logical_json_bytes),
            step_result_row_count=int(result_measurement.row_count),
            step_result_stored_json_bytes=int(result_measurement.stored_json_bytes),
            step_result_logical_json_bytes=int(result_measurement.logical_json_bytes),
            result_file_row_count=int(result_file_measurement.row_count),
            result_file_logical_json_bytes=int(
                result_file_measurement.logical_json_bytes
            ),
            runtime_input_file_row_count=int(runtime_input_file_measurement.row_count),
            runtime_input_file_logical_json_bytes=int(
                runtime_input_file_measurement.logical_json_bytes
            ),
        )

    async def measure_step_attempt_evidence(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> StepAttemptEvidenceSize:
        """Size a run's attempt evidence without materializing any of it.

        One aggregate over the run's attempts, so a caller can refuse or narrow
        the work before the JSON is fetched, decoded and copied. `pg_column_size`
        reports the *stored* size, which TOAST may have compressed, so treat it
        as a floor on the serialized cost rather than an exact byte count.
        """
        # Every RAG payload stores its own passage-byte aggregate, so the exact
        # passage total is one jsonb field extraction away — no payload is
        # decoded or materialized to measure it. The shared guarded expression
        # keeps a malformed persisted value from failing the statement, and
        # counts it as corruption instead of silently measuring zero.
        recorded_passage_bytes, is_corrupt = _recorded_passage_byte_expressions()
        candidate_stmt = (
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            candidate_stmt = candidate_stmt.limit(candidate_limit)
        candidates = candidate_stmt.subquery()
        row = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("attempt_count"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.func.pg_column_size(FlowStepAttempts.provenance_json)
                        ),
                        0,
                    ).label("provenance_bytes"),
                    sa.func.coalesce(
                        sa.func.sum(
                            sum(
                                (
                                    sa.func.coalesce(sa.func.pg_column_size(column), 0)
                                    for column in (
                                        FlowStepAttempts.provenance_json,
                                        FlowStepAttempts.input_payload_json,
                                        FlowStepAttempts.output_payload_json,
                                        FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb,
                                    )
                                ),
                                start=sa.literal(0),
                            )
                        ),
                        0,
                    ).label("stored_json_bytes"),
                    sa.func.coalesce(
                        sa.func.sum(_attempt_evidence_logical_bytes()),
                        0,
                    ).label("logical_json_bytes"),
                    sa.func.coalesce(sa.func.sum(recorded_passage_bytes), 0).label(
                        "passage_bytes"
                    ),
                    sa.func.coalesce(
                        sa.func.sum(sa.case((is_corrupt, 1), else_=0)), 0
                    ).label("corrupt_aggregates"),
                )
                .select_from(FlowStepAttempts)
                .outerjoin(
                    FlowStepAttemptResolvedInputs,
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id
                    == FlowStepAttempts.id,
                )
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.tenant_id == tenant_id)
                .where(FlowStepAttempts.id.in_(sa.select(candidates.c.id)))
            )
        ).one()
        return StepAttemptEvidenceSize(
            attempt_count=int(row.attempt_count),
            stored_provenance_bytes=int(row.provenance_bytes),
            recorded_passage_bytes=int(row.passage_bytes),
            stored_json_bytes=int(row.stored_json_bytes),
            logical_json_bytes=int(row.logical_json_bytes),
            corrupt_passage_aggregates=int(row.corrupt_aggregates),
        )

    async def list_step_attempts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
        logical_byte_budget: int | None = None,
        passage_byte_budget: int | None = None,
    ) -> StepAttemptPage:
        """Attempts for a run, oldest first, with snapshot-consistent totals.

        With `limit`, one statement bounds current and recent candidates to
        `limit + 1`, deduplicates their overlap, then ranks current attempts
        first and history newest first. The extra candidate is a truncation
        sentinel. Admitted rows must also fit both cumulative budgets: logical
        attempt JSON bytes bound what materialization expands to, and exact
        recorded passage bytes independently bound retained passage text.
        Counts ride in the same statement even when nothing is admitted.
        """
        base = (
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
        )
        if limit is None:
            rows = (
                (
                    await self.session.execute(
                        base.order_by(
                            FlowStepAttempts.step_order.asc(),
                            FlowStepAttempts.attempt_no.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            attempts = [FlowStepAttempt.model_validate(row) for row in rows]
            # An unlimited read loads everything, so no current attempt can be
            # excluded and the current counts carry no signal.
            return StepAttemptPage(
                attempts=attempts,
                total_count=len(attempts),
                current_total=0,
                current_admitted=0,
                count_truncated=False,
            )

        if limit < 0:
            raise ValueError("Step attempt limit must be non-negative.")
        candidate_limit = limit + 1
        # Candidate branches project every value needed for admission while
        # their index-backed LIMIT is active. No later aggregate or window may
        # reopen the full attempt table merely to measure candidate evidence.
        logical_bytes = _attempt_evidence_logical_bytes()
        passage_bytes, is_corrupt = _recorded_passage_byte_expressions()

        current_candidates = (
            sa.select(
                FlowStepAttempts.id.label("attempt_id"),
                FlowStepAttempts.step_order.label("step_order"),
                FlowStepAttempts.attempt_no.label("attempt_no"),
                sa.literal(0).label("is_current"),
                logical_bytes.label("logical_bytes"),
                passage_bytes.label("passage_bytes"),
                is_corrupt.label("is_corrupt"),
            )
            .select_from(FlowStepResults)
            .join(
                FlowStepAttempts,
                sa.and_(
                    FlowStepAttempts.flow_run_id == FlowStepResults.flow_run_id,
                    FlowStepAttempts.step_id == FlowStepResults.step_id,
                    FlowStepAttempts.attempt_no == FlowStepResults.current_attempt_no,
                ),
            )
            .outerjoin(
                FlowStepAttemptResolvedInputs,
                FlowStepAttemptResolvedInputs.flow_step_attempt_id
                == FlowStepAttempts.id,
            )
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.tenant_id == tenant_id,
                FlowStepResults.current_attempt_no.is_not(None),
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.tenant_id == tenant_id,
            )
            .order_by(
                FlowStepResults.step_order.desc(),
                FlowStepAttempts.attempt_no.desc(),
            )
            .limit(candidate_limit)
        )
        recent_candidates = (
            sa.select(
                FlowStepAttempts.id.label("attempt_id"),
                FlowStepAttempts.step_order.label("step_order"),
                FlowStepAttempts.attempt_no.label("attempt_no"),
                sa.literal(1).label("is_current"),
                logical_bytes.label("logical_bytes"),
                passage_bytes.label("passage_bytes"),
                is_corrupt.label("is_corrupt"),
            )
            .select_from(FlowStepAttempts)
            .outerjoin(
                FlowStepAttemptResolvedInputs,
                FlowStepAttemptResolvedInputs.flow_step_attempt_id
                == FlowStepAttempts.id,
            )
            .where(
                FlowStepAttempts.flow_run_id == run_id,
                FlowStepAttempts.tenant_id == tenant_id,
            )
            .order_by(
                FlowStepAttempts.step_order.desc(),
                FlowStepAttempts.attempt_no.desc(),
            )
            .limit(candidate_limit)
        )
        candidate_branches = current_candidates.union_all(recent_candidates).subquery()
        deduplicated_candidates = (
            sa.select(
                candidate_branches.c.attempt_id,
                candidate_branches.c.step_order,
                candidate_branches.c.attempt_no,
                candidate_branches.c.is_current,
                candidate_branches.c.logical_bytes,
                candidate_branches.c.passage_bytes,
                candidate_branches.c.is_corrupt,
            )
            .distinct(candidate_branches.c.attempt_id)
            .order_by(
                candidate_branches.c.attempt_id,
                candidate_branches.c.is_current.asc(),
            )
            .subquery()
        )
        candidates = (
            sa.select(
                deduplicated_candidates.c.attempt_id,
                deduplicated_candidates.c.step_order,
                deduplicated_candidates.c.attempt_no,
                deduplicated_candidates.c.is_current,
                deduplicated_candidates.c.logical_bytes,
                deduplicated_candidates.c.passage_bytes,
                deduplicated_candidates.c.is_corrupt,
            )
            .order_by(
                deduplicated_candidates.c.is_current.asc(),
                deduplicated_candidates.c.step_order.desc(),
                deduplicated_candidates.c.attempt_no.desc(),
            )
            .limit(candidate_limit)
            .subquery()
        )
        admission_order = (
            candidates.c.is_current.asc(),
            candidates.c.step_order.desc(),
            candidates.c.attempt_no.desc(),
        )
        ranked = (
            sa.select(
                candidates.c.attempt_id,
                candidates.c.step_order,
                candidates.c.is_current,
                sa.case((candidates.c.is_corrupt, 1), else_=0).label("is_corrupt"),
                sa.func.row_number().over(order_by=admission_order).label("row_rank"),
                sa.func.sum(candidates.c.logical_bytes)
                .over(order_by=admission_order)
                .label("cumulative_logical"),
                sa.func.sum(candidates.c.passage_bytes)
                .over(order_by=admission_order)
                .label("cumulative_passages"),
            )
            .select_from(candidates)
            .subquery()
        )
        admitted = sa.select(ranked.c.attempt_id, ranked.c.is_current).where(
            ranked.c.row_rank <= limit
        )
        if logical_byte_budget is not None:
            admitted = admitted.where(
                ranked.c.cumulative_logical <= logical_byte_budget
            )
        if passage_byte_budget is not None:
            # A corrupt aggregate has an unknowable logical size; admitting it
            # under a size budget would be a silent bypass, so it is excluded
            # and reported instead.
            admitted = admitted.where(
                ranked.c.cumulative_passages <= passage_byte_budget
            ).where(ranked.c.is_corrupt == 0)
        admitted_sq = admitted.subquery()
        excluded_currents = (
            sa.select(
                sa.func.coalesce(
                    sa.func.array_agg(sa.distinct(ranked.c.step_order)).filter(
                        ranked.c.is_current == 0
                    ),
                    sa.literal([], sa.ARRAY(sa.Integer)),
                ).label("step_orders")
            )
            .select_from(
                ranked.outerjoin(
                    admitted_sq, admitted_sq.c.attempt_id == ranked.c.attempt_id
                )
            )
            .where(admitted_sq.c.attempt_id.is_(None))
            .subquery()
        )
        totals = (
            sa.select(
                sa.func.count().label("total_count"),
                sa.func.coalesce(sa.func.sum(1 - ranked.c.is_current), 0).label(
                    "current_total"
                ),
                sa.func.coalesce(sa.func.sum(ranked.c.is_corrupt), 0).label(
                    "corrupt_aggregates"
                ),
            )
            .select_from(ranked)
            .subquery()
        )
        admitted_attempt_lookup = (
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.id == admitted_sq.c.attempt_id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .limit(1)
            .lateral("admitted_attempt")
        )
        admitted_attempt = aliased(FlowStepAttempts, admitted_attempt_lookup)
        # The totals row always exists, so zero admission still reports the
        # run's counts from the same statement and snapshot.
        rows = (
            await self.session.execute(
                sa.select(
                    totals.c.total_count,
                    totals.c.current_total,
                    totals.c.corrupt_aggregates,
                    excluded_currents.c.step_orders,
                    admitted_attempt,
                    admitted_sq.c.is_current,
                )
                .select_from(totals)
                .outerjoin(excluded_currents, sa.literal(True))
                .outerjoin(admitted_sq, sa.literal(True))
                .outerjoin(
                    admitted_attempt_lookup,
                    sa.literal(True),
                )
            )
        ).all()
        total_count = int(rows[0][0]) if rows else 0
        current_total = int(rows[0][1]) if rows else 0
        corrupt_aggregates = int(rows[0][2]) if rows else 0
        raw_excluded_orders = cast(
            "Sequence[int]", rows[0][3] if rows and rows[0][3] is not None else ()
        )
        excluded_current_orders = tuple(
            sorted(int(order) for order in raw_excluded_orders)
        )
        attempts_with_flag = [
            (FlowStepAttempt.model_validate(row[4]), int(row[5]))
            for row in rows
            if row[4] is not None
        ]
        current_admitted = sum(1 for _, flag in attempts_with_flag if flag == 0)
        attempts = [attempt for attempt, _ in attempts_with_flag]
        attempts.sort(key=lambda item: (item.step_order, item.attempt_no))
        return StepAttemptPage(
            attempts=attempts,
            total_count=total_count,
            current_total=current_total,
            current_admitted=current_admitted,
            count_truncated=total_count > limit,
            current_step_orders_not_loaded=excluded_current_orders,
            corrupt_passage_aggregates=corrupt_aggregates,
        )

    async def list_step_input_file_ids(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        attempt_no: int,
    ) -> list[UUID]:
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunStepInputFiles.file_id)
                    .where(FlowRunStepInputFiles.flow_run_id == run_id)
                    .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                    .where(FlowRunStepInputFiles.step_id == step_id)
                    .where(FlowRunStepInputFiles.attempt_no == attempt_no)
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def list_current_step_input_file_ids_by_step_result_id(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_results: Sequence[FlowStepResult],
    ) -> dict[UUID, Sequence[UUID]]:
        step_result_id_by_step_attempt, current_attempt_pairs = (
            _current_step_attempt_pairs_by_result_id(step_results)
        )
        if not current_attempt_pairs:
            return {}

        rows = (
            await self.session.execute(
                sa.select(
                    FlowRunStepInputFiles.step_id,
                    FlowRunStepInputFiles.attempt_no,
                    FlowRunStepInputFiles.file_id,
                )
                .where(FlowRunStepInputFiles.flow_run_id == run_id)
                .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                .where(
                    sa.tuple_(
                        FlowRunStepInputFiles.step_id,
                        FlowRunStepInputFiles.attempt_no,
                    ).in_(current_attempt_pairs)
                )
                .order_by(
                    FlowRunStepInputFiles.step_order.asc(),
                    FlowRunStepInputFiles.attempt_no.asc(),
                    FlowRunStepInputFiles.ordinal.asc(),
                )
            )
        ).all()

        file_ids_by_step_result_id: dict[UUID, list[UUID]] = {}
        for step_id, attempt_no, file_id in rows:
            step_result_id = step_result_id_by_step_attempt.get((step_id, attempt_no))
            if step_result_id is None:
                continue
            file_ids_by_step_result_id.setdefault(step_result_id, []).append(file_id)

        return {
            step_result_id: tuple(file_ids)
            for step_result_id, file_ids in file_ids_by_step_result_id.items()
        }

    async def list_current_step_input_file_metadata_by_step_result_id(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        step_results: Sequence[FlowStepResult],
        limit: int | None = None,
        logical_byte_budget: int | None = None,
    ) -> dict[UUID, tuple[FlowRunStepInputFileMetadata, ...]]:
        step_result_id_by_step_attempt, current_attempt_pairs = (
            _current_step_attempt_pairs_by_result_id(step_results)
        )
        if not current_attempt_pairs:
            return {}

        stmt = (
            sa.select(
                FlowRunStepInputFiles.step_id,
                FlowRunStepInputFiles.attempt_no,
                FlowRunStepInputFiles.file_id,
            )
            .join(Files, Files.id == FlowRunStepInputFiles.file_id)
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .where(FlowRunStepInputFiles.tenant_id == tenant_id)
            .where(
                sa.tuple_(
                    FlowRunStepInputFiles.step_id,
                    FlowRunStepInputFiles.attempt_no,
                ).in_(current_attempt_pairs)
            )
            .order_by(
                FlowRunStepInputFiles.step_order.asc(),
                FlowRunStepInputFiles.attempt_no.asc(),
                FlowRunStepInputFiles.ordinal.asc(),
            )
        )
        if limit is not None and logical_byte_budget is not None:
            candidates = (
                sa.select(
                    FlowRunStepInputFiles.id.label("row_id"),
                    FlowRunStepInputFiles.step_order.label("step_order"),
                    FlowRunStepInputFiles.attempt_no.label("attempt_no"),
                    FlowRunStepInputFiles.ordinal.label("ordinal"),
                    _file_evidence_logical_bytes().label("logical_bytes"),
                )
                .join(Files, Files.id == FlowRunStepInputFiles.file_id)
                .where(FlowRunStepInputFiles.flow_run_id == run_id)
                .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                .where(
                    sa.tuple_(
                        FlowRunStepInputFiles.step_id,
                        FlowRunStepInputFiles.attempt_no,
                    ).in_(current_attempt_pairs)
                )
                .order_by(
                    FlowRunStepInputFiles.step_order.asc(),
                    FlowRunStepInputFiles.attempt_no.asc(),
                    FlowRunStepInputFiles.ordinal.asc(),
                    FlowRunStepInputFiles.id.asc(),
                )
                .limit(limit + 1)
                .subquery()
            )
            order = (
                candidates.c.step_order,
                candidates.c.attempt_no,
                candidates.c.ordinal,
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
                FlowRunStepInputFiles.id.in_(
                    sa.select(ranked.c.row_id).where(
                        ranked.c.row_rank <= limit,
                        ranked.c.cumulative_logical <= logical_byte_budget,
                    )
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).all()
        ordered_file_ids = list(dict.fromkeys(row.file_id for row in rows))
        if not ordered_file_ids:
            return {}

        file_repo = FileRepository(self.session)
        files = await file_repo.get_by_ids(ordered_file_ids)
        file_by_id = {file.id: file for file in files}
        references = await file_repo.get_content_references(ordered_file_ids)
        references_by_file_id: dict[UUID, list[FileContentReferenceRecord]] = {
            file_id: [] for file_id in ordered_file_ids
        }
        for reference in references:
            references_by_file_id[reference.file_id].append(reference)

        metadata_by_step_result_id: dict[UUID, list[FlowRunStepInputFileMetadata]] = {}
        for row in rows:
            step_result_id = step_result_id_by_step_attempt.get(
                (row.step_id, row.attempt_no)
            )
            if step_result_id is None:
                continue
            file = file_by_id.get(row.file_id)
            if file is None:
                continue
            file_references = references_by_file_id[row.file_id]
            primary_reference = select_primary_file_reference(
                file.file_type,
                file_references,
            )
            if primary_reference is None:
                continue
            file_info = project_file_info(file, file_references)
            text_reference = next(
                (
                    reference
                    for reference in file_references
                    if reference.variant is FileContentVariant.EXTRACTED_TEXT
                ),
                None,
            )
            if text_reference is None and file.file_type is FileType.TEXT:
                text_reference = primary_reference
            transcription_reference = next(
                (
                    reference
                    for reference in file_references
                    if reference.variant is FileContentVariant.TRANSCRIPTION
                ),
                None,
            )
            metadata_by_step_result_id.setdefault(step_result_id, []).append(
                FlowRunStepInputFileMetadata(
                    file_id=row.file_id,
                    name=file_info.name,
                    checksum=file_info.checksum,
                    size=file_info.size,
                    mimetype=file_info.mimetype,
                    file_type=file_info.file_type,
                    text_size_bytes=(
                        text_reference.size_bytes
                        if text_reference is not None
                        else None
                    ),
                    has_text=(
                        text_reference is not None and text_reference.size_bytes > 0
                    ),
                    has_transcription=(
                        transcription_reference is not None
                        and transcription_reference.size_bytes > 0
                    ),
                )
            )

        return {
            step_result_id: tuple(metadata)
            for step_result_id, metadata in metadata_by_step_result_id.items()
        }

    async def list_result_files(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
        logical_byte_budget: int | None = None,
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
        if limit is not None and logical_byte_budget is not None:
            candidates = (
                sa.select(
                    FlowRunStepResultFiles.id.label("row_id"),
                    FlowRunStepResultFiles.step_order.label("step_order"),
                    FlowRunStepResultFiles.attempt_no.label("attempt_no"),
                    FlowRunStepResultFiles.ordinal.label("ordinal"),
                    _file_evidence_logical_bytes().label("logical_bytes"),
                )
                .join(Files, Files.id == FlowRunStepResultFiles.file_id)
                .where(FlowRunStepResultFiles.flow_run_id == run_id)
                .where(FlowRunStepResultFiles.tenant_id == tenant_id)
                .order_by(
                    FlowRunStepResultFiles.step_order.asc(),
                    FlowRunStepResultFiles.attempt_no.asc(),
                    FlowRunStepResultFiles.ordinal.asc(),
                    FlowRunStepResultFiles.id.asc(),
                )
                .limit(limit + 1)
                .subquery()
            )
            order = (
                candidates.c.step_order,
                candidates.c.attempt_no,
                candidates.c.ordinal,
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
                FlowRunStepResultFiles.id.in_(
                    sa.select(ranked.c.row_id).where(
                        ranked.c.row_rank <= limit,
                        ranked.c.cumulative_logical <= logical_byte_budget,
                    )
                )
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return await self._project_result_file_rows(rows)

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
            .join(
                FlowStepResults,
                sa.and_(
                    FlowStepResults.id == FlowRunStepResultFiles.step_result_id,
                    FlowStepResults.flow_run_id == FlowRunStepResultFiles.flow_run_id,
                    FlowStepResults.step_id == FlowRunStepResultFiles.step_id,
                    FlowStepResults.current_attempt_no
                    == FlowRunStepResultFiles.attempt_no,
                ),
            )
            .where(FlowRunStepResultFiles.flow_run_id.in_(unique_run_ids))
            .where(FlowRunStepResultFiles.tenant_id == tenant_id)
            .order_by(
                FlowRunStepResultFiles.flow_run_id.asc(),
                FlowRunStepResultFiles.step_order.asc(),
                FlowRunStepResultFiles.ordinal.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return await self._project_result_file_rows(rows)

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
        projected = await self._project_result_file_rows([row])
        return projected[0]

    async def _project_result_file_rows(
        self,
        rows: Sequence[Any],
    ) -> list[FlowRunStepResultFile]:
        file_ids = list(dict.fromkeys(file_row.id for _, file_row in rows))
        references = await FileRepository(self.session).get_content_references(file_ids)
        references_by_file_id: dict[UUID, list[FileContentReferenceRecord]] = {
            file_id: [] for file_id in file_ids
        }
        for reference in references:
            references_by_file_id[reference.file_id].append(reference)

        projected: list[FlowRunStepResultFile] = []
        for result_file_row, file_row in rows:
            projected.append(
                _result_file_from_rows(
                    result_file_row,
                    FileMetadata.model_validate(file_row),
                    references_by_file_id[file_row.id],
                )
            )
        return projected

    async def mark_running_if_claimable(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        expected_revision: int,
    ) -> bool:
        now_utc = datetime.now(timezone.utc)
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.revision == expected_revision)
            .values(
                status=FlowRunStatus.RUNNING.value,
                started_at=sa.func.coalesce(FlowRuns.started_at, now_utc),
                dispatched_at=sa.func.coalesce(FlowRuns.dispatched_at, now_utc),
                dispatch_next_attempt_at=None,
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
        return FlowStepResult.model_validate(row)

    async def save_step_result(
        self,
        flow_run_id: UUID,
        result: FlowStepResult,
        tenant_id: UUID,
        *,
        session: AsyncSession | None = None,
        attempt_no: int | None,
        result_file_references: Sequence[FlowStepResultFileReference] | None = None,
    ) -> FlowStepResult | None:
        """Persist a step result and optionally replace this attempt's file rows.

        Returns the persisted result, or None when the parent run is already terminal.
        A `result_file_references` value of None leaves file rows untouched for
        non-success updates; an empty sequence intentionally clears them.
        """
        db_session = session or self.session

        if result.status == FlowStepResultStatus.COMPLETED and attempt_no is None:
            raise ValueError("attempt_no is required for completed Flow step results.")
        result_file_attempt_no: int | None = None
        if result_file_references is not None and attempt_no is None:
            raise ValueError("attempt_no is required for Flow step result files.")
        if result_file_references is not None:
            result_file_attempt_no = attempt_no

        payload: dict[str, Any] = {
            "flow_run_id": flow_run_id,
            "flow_id": result.flow_id,
            "tenant_id": tenant_id,
            "step_id": result.step_id,
            "step_order": result.step_order,
            "assistant_id": result.assistant_id,
            "input_payload_json": result.input_payload_json,
            "effective_prompt": result.effective_prompt,
            "output_payload_json": result.output_payload_json,
            "model_parameters_json": result.model_parameters_json,
            "num_tokens_input": result.num_tokens_input,
            "num_tokens_output": result.num_tokens_output,
            "status": result.status.value,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "flow_step_execution_hash": result.flow_step_execution_hash,
        }

        if result.status in (
            FlowStepResultStatus.COMPLETED,
            FlowStepResultStatus.FAILED,
            FlowStepResultStatus.CANCELLED,
        ):
            payload["finished_at"] = datetime.now(timezone.utc)
        if result.status == FlowStepResultStatus.COMPLETED:
            payload["current_attempt_no"] = attempt_no

        active_run_exists = (
            sa.select(sa.literal(1))
            .select_from(FlowRuns)
            .where(FlowRuns.id == flow_run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
            .exists()
        )

        step_result_mapper = cast(Mapper[FlowStepResults], sa.inspect(FlowStepResults))
        insert_values = (
            cast(
                sa.ColumnElement[object],
                sa.bindparam(
                    column_name,
                    cast(object, value),
                    type_=step_result_mapper.columns[column_name].type,
                ),
            )
            for column_name, value in payload.items()
        )
        insert_projection = sa.select(*insert_values).where(active_run_exists)
        stmt = (
            pg_insert(FlowStepResults)
            .from_select(tuple(payload), insert_projection)
            .on_conflict_do_update(
                constraint="uq_flow_step_results_run_step",
                set_=payload,
                where=active_run_exists,
            )
            .returning(FlowStepResults)
        )
        saved = await db_session.scalar(stmt)
        if saved is None:
            return None
        if result_file_references is not None:
            assert result_file_attempt_no is not None
            await self._replace_step_result_file_rows(
                db_session=db_session,
                result_row=saved,
                result_file_references=result_file_references,
                attempt_no=result_file_attempt_no,
            )
        return FlowStepResult.model_validate(saved)

    async def _replace_step_result_file_rows(
        self,
        *,
        db_session: AsyncSession,
        result_row: FlowStepResults,
        result_file_references: Sequence[FlowStepResultFileReference],
        attempt_no: int,
    ) -> None:
        await db_session.execute(
            sa.delete(FlowRunStepResultFiles)
            .where(FlowRunStepResultFiles.step_result_id == result_row.id)
            .where(FlowRunStepResultFiles.tenant_id == result_row.tenant_id)
            .where(FlowRunStepResultFiles.attempt_no == attempt_no)
        )
        if not result_file_references:
            return

        rows = [
            {
                "flow_run_id": result_row.flow_run_id,
                "flow_id": result_row.flow_id,
                "tenant_id": result_row.tenant_id,
                "step_result_id": result_row.id,
                "step_id": result_row.step_id,
                "step_order": result_row.step_order,
                "attempt_no": attempt_no,
                "file_id": reference.file_id,
                "ordinal": ordinal,
                "source": reference.source,
            }
            for ordinal, reference in enumerate(result_file_references)
        ]
        await db_session.execute(sa.insert(FlowRunStepResultFiles).values(rows))

    async def claim_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        run_status = await self.session.scalar(
            sa.select(FlowRuns.status)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_status not in self._ACTIVE_STATUSES:
            return None

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
                error_code=None,
                error_message=None,
                started_at=sa.func.coalesce(FlowStepResults.started_at, now_utc),
                finished_at=None,
            )
            .returning(FlowStepResults)
        )
        if row is None:
            return None
        return FlowStepResult.model_validate(row)

    async def allocate_next_attempt_no(
        self,
        *,
        tenant_id: UUID,
        flow_run_id: UUID,
        step_id: UUID,
    ) -> int:
        return await next_step_attempt_no(
            self.session,
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
        run_status = await self.session.scalar(
            sa.select(FlowRuns.status)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .with_for_update()
        )
        if run_status not in self._ACTIVE_STATUSES:
            raise FlowRunPersistenceInvariantError(
                operation="create_flow_step_attempt",
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )

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
            raise FlowRunPersistenceInvariantError(
                operation="create_flow_step_attempt",
                run_id=run_id,
                tenant_id=tenant_id,
                flow_id=flow_id,
            )
        return FlowStepAttempt.model_validate(row)

    async def copy_step_input_files_from_predecessor_attempt(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        predecessor_attempt_id: UUID | None,
        target_attempt_no: int,
    ) -> None:
        if predecessor_attempt_id is None:
            return
        target_exists = await self.session.scalar(
            sa.select(sa.literal(True))
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .where(FlowRunStepInputFiles.tenant_id == tenant_id)
            .where(FlowRunStepInputFiles.step_id == step_id)
            .where(FlowRunStepInputFiles.attempt_no == target_attempt_no)
            .limit(1)
        )
        if target_exists:
            return

        source_attempt_no = await self.session.scalar(
            sa.select(FlowStepAttempts.attempt_no)
            .where(FlowStepAttempts.id == predecessor_attempt_id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.flow_id == flow_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.step_id == step_id)
        )
        if source_attempt_no is None:
            return

        file_ids = (
            (
                await self.session.execute(
                    sa.select(FlowRunStepInputFiles.file_id)
                    .where(FlowRunStepInputFiles.flow_run_id == run_id)
                    .where(FlowRunStepInputFiles.tenant_id == tenant_id)
                    .where(FlowRunStepInputFiles.step_id == step_id)
                    .where(FlowRunStepInputFiles.attempt_no == source_attempt_no)
                    .order_by(FlowRunStepInputFiles.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        if not file_ids:
            return

        rows = build_step_input_file_rows(
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            attempt_no=target_attempt_no,
            projections=[
                {
                    "step_id": step_id,
                    "step_order": step_order,
                    "file_ids": list(file_ids),
                }
            ],
        )
        # The source attempt row already holds the runtime-upload FK, so the
        # referenced upload cannot disappear while this copy is inserted.
        await self.session.execute(
            pg_insert(FlowRunStepInputFiles)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_flow_run_step_input_files_run_step_attempt_file"
            )
        )

    async def activate_step_attempt(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        resolved_input_edges: FlowResolvedInputEdges,
        attempt_input: FlowStepAttemptInput | None,
    ) -> FlowStepAttempt | None:
        row = await self.session.scalar(
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if row is None:
            return None
        merged_attempt_input: FlowStepAttemptInput | None = None
        if attempt_input is not None:
            require_attempt_runtime_evidence_not_purged(
                row.provenance_json,
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
            )
            merged_attempt_input = merge_flow_step_attempt_input(
                row.input_payload_json,
                attempt_input,
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
            )
        created = await self._record_resolved_input_edges_for_locked_attempt(
            attempt_id=row.id,
            attempt_status=row.status,
            tenant_id=tenant_id,
            aggregate=resolved_input_edges,
        )
        if created is None:
            return None
        if merged_attempt_input is not None:
            row.input_payload_json = merged_attempt_input.to_payload()
            if merged_attempt_input.start is not None:
                row.requested_model = merged_attempt_input.start.requested_model
                row.provider = merged_attempt_input.start.provider
        await self.session.flush()
        await self.session.refresh(row)
        return FlowStepAttempt.model_validate(row)

    async def get_resolved_input_edges(
        self,
        *,
        attempt_id: UUID,
        tenant_id: UUID,
    ) -> FlowResolvedInputEdgesParseResult | None:
        row = (
            await self.session.execute(
                sa.select(FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb)
                .select_from(FlowStepAttempts)
                .outerjoin(
                    FlowStepAttemptResolvedInputs,
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id
                    == FlowStepAttempts.id,
                )
                .where(FlowStepAttempts.id == attempt_id)
                .where(FlowStepAttempts.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return parse_resolved_input_edges(row[0])

    async def list_resolved_input_edges_by_attempt_id(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        attempt_ids: Sequence[UUID],
    ) -> dict[UUID, FlowResolvedInputEdgesParseResult]:
        """Read exact lineage for an admitted attempt set in one statement."""
        if not attempt_ids:
            return {}
        rows = (
            await self.session.execute(
                sa.select(
                    FlowStepAttempts.id,
                    FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb,
                )
                .select_from(FlowStepAttempts)
                .outerjoin(
                    FlowStepAttemptResolvedInputs,
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id
                    == FlowStepAttempts.id,
                )
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.tenant_id == tenant_id)
                .where(FlowStepAttempts.id.in_(attempt_ids))
            )
        ).all()
        return {
            attempt_id: parse_resolved_input_edges(raw_resolved_inputs)
            for attempt_id, raw_resolved_inputs in rows
        }

    async def _record_resolved_input_edges_for_locked_attempt(
        self,
        *,
        attempt_id: UUID,
        attempt_status: str,
        tenant_id: UUID,
        aggregate: FlowResolvedInputEdges,
    ) -> bool | None:
        raw_existing = await self.session.scalar(
            sa.select(FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb).where(
                FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt_id
            )
        )
        existing = parse_resolved_input_edges(raw_existing)
        if existing.status == "corrupt":
            assert existing.marker is not None
            raise FlowResolvedInputEdgesUnavailableError(
                attempt_id=attempt_id,
                tenant_id=tenant_id,
                error_code=existing.marker.error_code,
            )
        if existing.status == "tracked":
            assert existing.aggregate is not None
            if existing.aggregate == aggregate:
                return False
            raise FlowResolvedInputEdgesConflictError(
                attempt_id=attempt_id,
                tenant_id=tenant_id,
            )
        if attempt_status not in OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES:
            return None

        await self.session.execute(
            sa.insert(FlowStepAttemptResolvedInputs).values(
                flow_step_attempt_id=attempt_id,
                resolved_input_edges_jsonb=aggregate.model_dump(mode="json"),
            )
        )
        return True

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
        attempt_input: FlowStepAttemptInput | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
    ) -> FlowStepAttempt | None:
        row = await self.session.scalar(
            sa.select(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status.in_(OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if row is None:
            return None
        terminalization_evidence = resolve_attempt_terminalization_evidence(
            row.provenance_json,
            provenance_json,
        )
        merged_attempt_input = (
            merge_flow_step_attempt_input(
                row.input_payload_json,
                attempt_input,
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
            )
            if attempt_input is not None
            and terminalization_evidence.write_runtime_payloads
            else None
        )
        canonical_attempt_input = merged_attempt_input
        if canonical_attempt_input is None:
            canonical_attempt_input = parse_flow_step_attempt_input(
                row.input_payload_json
            ).attempt_input
        canonical_start = (
            canonical_attempt_input.start
            if canonical_attempt_input is not None
            else None
        )
        row.status = status.value
        row.error_code = error_code
        row.error_message = error_message
        row.requested_model = (
            canonical_start.requested_model
            if canonical_start is not None
            else requested_model
        )
        row.response_model = response_model
        row.provider = (
            canonical_start.provider if canonical_start is not None else provider
        )
        row.finish_reason = finish_reason
        row.provider_response_id = provider_response_id
        row.num_tokens_input = num_tokens_input
        row.num_tokens_output = num_tokens_output
        row.provenance_json = terminalization_evidence.provenance_json
        if terminalization_evidence.write_runtime_payloads:
            if merged_attempt_input is not None:
                row.input_payload_json = merged_attempt_input.to_payload()
            row.output_payload_json = output_payload_json
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(row)
        if status == FlowStepAttemptStatus.COMPLETED:
            await self._mark_predecessor_superseded_by_attempt(
                completed_attempt_row=row,
                tenant_id=tenant_id,
            )
        return FlowStepAttempt.model_validate(row)

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
    file: FileMetadata,
    references: list[FileContentReferenceRecord],
) -> FlowRunStepResultFile:
    primary = select_primary_file_reference(file.file_type, references)
    if primary is None:
        raise FlowRunPersistenceInvariantError(
            operation="project_flow_result_file_content",
            run_id=result_file_row.flow_run_id,
            tenant_id=result_file_row.tenant_id,
            flow_id=result_file_row.flow_id,
        )
    info = project_file_info(file, references)
    availability: FlowRunStepResultFileAvailability = (
        "available" if primary.state is ContentState.AVAILABLE else "content_purged"
    )
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
        name=info.name,
        checksum=info.checksum,
        size=info.size,
        mimetype=info.mimetype,
        file_type=info.file_type,
        availability=availability,
    )
