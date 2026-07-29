from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
)
from eneo.flows.domain.provider_call import (
    ProviderCall,
    ProviderCallCompletion,
    ProviderCallEvidence,
    ProviderCallEvidencePage,
    ProviderCallRejectionReason,
    ProviderCallRequest,
    ProviderCallStatus,
    ProviderCallUnknownReason,
)
from eneo.flows.enums import FlowStepAttemptStatus
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdgeIndexes,
    parse_resolved_input_edges,
)

_RESOLVED_INPUT_EDGE_INDEXES_ADAPTER: TypeAdapter[FlowResolvedInputEdgeIndexes] = (
    TypeAdapter(FlowResolvedInputEdgeIndexes)
)


class FlowProviderCallAttemptNotOpenError(RuntimeError):
    pass


class FlowProviderCallNotFoundError(RuntimeError):
    pass


class FlowProviderCallStateConflictError(RuntimeError):
    pass


class FlowProviderCallResolvedInputLinkError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FlowProviderCallEvidenceMeasurement:
    row_count: int
    logical_json_bytes: int = 0

    @classmethod
    def empty(cls) -> "FlowProviderCallEvidenceMeasurement":
        return cls(row_count=0, logical_json_bytes=0)


def _provider_call_evidence_logical_bytes() -> ColumnElement[int]:
    # Paired with `_to_evidence`: mapped_source_id is the projection's only
    # unbounded scalar and must be measured as serialized JSON, including escapes.
    return sa.func.coalesce(
        sa.func.octet_length(
            sa.cast(sa.func.to_jsonb(FlowProviderCalls.mapped_source_id), sa.Text)
        ),
        0,
    )


class FlowProviderCallRepository:
    """Owns ordered provider-call lifecycle rows under a Flow step attempt."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def measure_evidence_row_count(
        self, *, run_id: UUID, tenant_id: UUID, ceiling: int
    ) -> int:
        candidates = (
            sa.select(FlowProviderCalls.id)
            .join(
                FlowStepAttempts,
                FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
            )
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .limit(ceiling + 1)
            .subquery()
        )
        return int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(candidates)
            )
            or 0
        )

    async def measure_evidence(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> FlowProviderCallEvidenceMeasurement:
        candidate_stmt = (
            sa.select(FlowProviderCalls.id)
            .select_from(FlowProviderCalls)
            .join(
                FlowStepAttempts,
                FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
            )
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            candidate_stmt = candidate_stmt.limit(candidate_limit)
        candidates = candidate_stmt.subquery()
        row = (
            await self.session.execute(
                sa.select(
                    sa.func.count().label("row_count"),
                    sa.func.coalesce(
                        sa.func.sum(_provider_call_evidence_logical_bytes()), 0
                    ).label("logical_json_bytes"),
                )
                .select_from(FlowProviderCalls)
                .where(FlowProviderCalls.id.in_(sa.select(candidates.c.id)))
            )
        ).one()
        return FlowProviderCallEvidenceMeasurement(
            row_count=int(row.row_count),
            logical_json_bytes=int(row.logical_json_bytes),
        )

    async def get_call(self, *, call_id: UUID) -> ProviderCall:
        row = await self.session.scalar(
            sa.select(FlowProviderCalls).where(FlowProviderCalls.id == call_id)
        )
        if row is None:
            raise FlowProviderCallNotFoundError(
                f"Flow provider call {call_id} was not found."
            )
        return ProviderCall.model_validate(row)

    async def list_evidence_page(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int,
        after_event_id: UUID | None = None,
        attempt_id: UUID | None = None,
        total_count_limit: int | None = None,
        logical_byte_budget: int | None = None,
    ) -> ProviderCallEvidencePage:
        if limit < 1:
            raise ValueError("Provider-call evidence limit must be positive.")

        predicates = [
            FlowStepAttempts.flow_run_id == run_id,
            FlowStepAttempts.tenant_id == tenant_id,
        ]
        if attempt_id is not None:
            predicates.append(FlowStepAttempts.id == attempt_id)

        count_stmt = (
            sa.select(FlowProviderCalls.id)
            .select_from(FlowProviderCalls)
            .join(
                FlowStepAttempts,
                FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
            )
            .where(*predicates)
        )
        if total_count_limit is not None:
            count_stmt = count_stmt.limit(total_count_limit)
        total_count = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(count_stmt.subquery())
            )
            or 0
        )
        total_count_truncated = (
            total_count_limit is not None and total_count == total_count_limit
        )

        page_predicates = list(predicates)
        if after_event_id is not None:
            cursor = (
                await self.session.execute(
                    sa.select(
                        FlowStepAttempts.step_order,
                        FlowStepAttempts.attempt_no,
                        FlowProviderCalls.ordinal,
                        FlowProviderCalls.id,
                    )
                    .select_from(FlowProviderCalls)
                    .join(
                        FlowStepAttempts,
                        FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
                    )
                    .where(*predicates)
                    .where(FlowProviderCalls.id == after_event_id)
                )
            ).one_or_none()
            if cursor is None:
                raise FlowProviderCallNotFoundError(
                    "The provider-call evidence cursor was not found."
                )
            page_predicates.append(
                sa.tuple_(
                    FlowStepAttempts.step_order,
                    FlowStepAttempts.attempt_no,
                    FlowProviderCalls.ordinal,
                    FlowProviderCalls.id,
                )
                > sa.tuple_(*cursor)
            )

        admitted_ids = None
        if logical_byte_budget is not None:
            candidates = (
                sa.select(
                    FlowProviderCalls.id.label("row_id"),
                    FlowStepAttempts.step_order.label("step_order"),
                    FlowStepAttempts.attempt_no.label("attempt_no"),
                    FlowProviderCalls.ordinal.label("ordinal"),
                    _provider_call_evidence_logical_bytes().label("logical_bytes"),
                )
                .join(
                    FlowStepAttempts,
                    FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
                )
                .where(*page_predicates)
                .order_by(
                    FlowStepAttempts.step_order.asc(),
                    FlowStepAttempts.attempt_no.asc(),
                    FlowProviderCalls.ordinal.asc(),
                    FlowProviderCalls.id.asc(),
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
            admitted_ids = sa.select(ranked.c.row_id).where(
                ranked.c.row_rank <= limit,
                ranked.c.cumulative_logical <= logical_byte_budget,
            )

        row_stmt = (
            sa.select(
                FlowProviderCalls,
                FlowStepAttempts.step_id,
                FlowStepAttempts.step_order,
                FlowStepAttempts.attempt_no,
            )
            .join(
                FlowStepAttempts,
                FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
            )
            .where(*page_predicates)
        )
        if admitted_ids is not None:
            row_stmt = row_stmt.where(FlowProviderCalls.id.in_(admitted_ids))
        rows = (
            await self.session.execute(
                row_stmt.order_by(
                    FlowStepAttempts.step_order.asc(),
                    FlowStepAttempts.attempt_no.asc(),
                    FlowProviderCalls.ordinal.asc(),
                    FlowProviderCalls.id.asc(),
                ).limit(limit + 1 if admitted_ids is None else limit)
            )
        ).all()
        has_more = (
            len(rows) > limit
            if admitted_ids is None
            else bool(rows) and total_count > len(rows)
        )
        visible_rows = rows[:limit]
        items = tuple(
            _to_evidence(
                call=row[0],
                step_id=row[1],
                step_order=row[2],
                attempt_no=row[3],
            )
            for row in visible_rows
        )
        return ProviderCallEvidencePage(
            items=items,
            count=len(items),
            total_count=total_count,
            total_count_truncated=total_count_truncated,
            has_more=has_more,
            next_after_event_id=items[-1].event_id if has_more else None,
        )

    async def mark_started_calls_outcome_unknown_for_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        reason: ProviderCallUnknownReason,
    ) -> int:
        attempt_ids = sa.select(FlowStepAttempts.id).where(
            FlowStepAttempts.flow_run_id == run_id,
            FlowStepAttempts.tenant_id == tenant_id,
        )
        now = datetime.now(timezone.utc)
        result = await self.session.scalars(
            sa.update(FlowProviderCalls)
            .where(FlowProviderCalls.flow_step_attempt_id.in_(attempt_ids))
            .where(FlowProviderCalls.status == ProviderCallStatus.STARTED.value)
            .values(
                status=ProviderCallStatus.OUTCOME_UNKNOWN.value,
                outcome_reason=ProviderCallUnknownReason(reason).value,
                finished_at=now,
                updated_at=now,
            )
            .returning(FlowProviderCalls.id)
        )
        return len(result.all())

    async def start_call_for_execution(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        request: ProviderCallRequest,
        resolved_input_edge_indexes: FlowResolvedInputEdgeIndexes,
    ) -> ProviderCall:
        attempt_id, resolved_input_edge_count = await self._lock_open_attempt(
            FlowStepAttempts.flow_run_id == run_id,
            FlowStepAttempts.step_id == step_id,
            FlowStepAttempts.attempt_no == attempt_no,
            FlowStepAttempts.tenant_id == tenant_id,
        )
        return await self._insert_started_call(
            attempt_id=attempt_id,
            request=request,
            resolved_input_edge_indexes=self._validate_resolved_input_edge_indexes(
                indexes=resolved_input_edge_indexes,
                resolved_input_edge_count=resolved_input_edge_count,
            ),
        )

    async def _lock_open_attempt(
        self,
        *identity_predicates: ColumnElement[bool],
    ) -> tuple[UUID, int]:
        row = (
            await self.session.execute(
                sa.select(
                    FlowStepAttempts.id,
                    FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb,
                )
                .outerjoin(
                    FlowStepAttemptResolvedInputs,
                    FlowStepAttemptResolvedInputs.flow_step_attempt_id
                    == FlowStepAttempts.id,
                )
                .where(*identity_predicates)
                .where(FlowStepAttempts.status == FlowStepAttemptStatus.STARTED.value)
                .with_for_update(of=FlowStepAttempts)
            )
        ).one_or_none()
        if row is None:
            raise FlowProviderCallAttemptNotOpenError(
                "The Flow step attempt is not open for a provider call."
            )
        attempt_id, raw_resolved_input_edges = row
        if raw_resolved_input_edges is None:
            raise FlowProviderCallResolvedInputLinkError(
                "Provider I/O cannot start before resolved input evidence is activated."
            )
        parsed = parse_resolved_input_edges(raw_resolved_input_edges)
        if parsed.status != "tracked" or parsed.aggregate is None:
            raise FlowProviderCallResolvedInputLinkError(
                "Provider I/O cannot start with corrupt resolved input evidence."
            )
        return attempt_id, len(parsed.aggregate.edges)

    @staticmethod
    def _validate_resolved_input_edge_indexes(
        *,
        indexes: FlowResolvedInputEdgeIndexes,
        resolved_input_edge_count: int,
    ) -> FlowResolvedInputEdgeIndexes:
        try:
            canonical_indexes = _RESOLVED_INPUT_EDGE_INDEXES_ADAPTER.validate_python(
                indexes
            )
        except ValidationError as exc:
            raise FlowProviderCallResolvedInputLinkError(
                "Provider-call resolved input indexes are not canonical."
            ) from exc
        if canonical_indexes and canonical_indexes[-1] >= resolved_input_edge_count:
            raise FlowProviderCallResolvedInputLinkError(
                "Provider-call resolved input indexes exceed the activated aggregate."
            )
        return canonical_indexes

    async def _insert_started_call(
        self,
        *,
        attempt_id: UUID,
        request: ProviderCallRequest,
        resolved_input_edge_indexes: FlowResolvedInputEdgeIndexes,
    ) -> ProviderCall:
        current_ordinal = await self.session.scalar(
            sa.select(sa.func.max(FlowProviderCalls.ordinal)).where(
                FlowProviderCalls.flow_step_attempt_id == attempt_id
            )
        )
        mapped_call = request.mapped_call
        row = await self.session.scalar(
            sa.insert(FlowProviderCalls)
            .values(
                flow_step_attempt_id=attempt_id,
                ordinal=(current_ordinal or 0) + 1,
                status=ProviderCallStatus.STARTED.value,
                request_schema_version=request.request_schema_version,
                provider_request_hash=request.provider_request_hash,
                requested_model=request.requested_model,
                provider=request.provider,
                response_format=request.response_format.value,
                requested_capabilities=[
                    capability.value for capability in request.requested_capabilities
                ],
                resolved_input_edge_indexes=list(resolved_input_edge_indexes),
                call_reason=request.call_reason.value,
                mapped_execution_mode=(
                    (
                        "per_source"
                        if mapped_call.execution_mode == "per_source_reader"
                        else mapped_call.execution_mode
                    )
                    if mapped_call is not None
                    else None
                ),
                mapped_item_index=(
                    mapped_call.item_index if mapped_call is not None else None
                ),
                mapped_source_index=(
                    mapped_call.source_index if mapped_call is not None else None
                ),
                mapped_source_id=(
                    mapped_call.source_id if mapped_call is not None else None
                ),
                requested_at=datetime.now(timezone.utc),
            )
            .returning(FlowProviderCalls)
        )
        if row is None:
            raise RuntimeError("Provider call insert returned no row.")
        return ProviderCall.model_validate(row)

    async def complete_call(
        self,
        *,
        call_id: UUID,
        receipt: ProviderCallCompletion,
    ) -> ProviderCall:
        row = await self.session.scalar(
            sa.select(FlowProviderCalls)
            .where(FlowProviderCalls.id == call_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if row is None:
            raise FlowProviderCallNotFoundError(
                f"Flow provider call {call_id} was not found."
            )
        if row.status == ProviderCallStatus.COMPLETED.value:
            if _completion_matches(row, receipt):
                return ProviderCall.model_validate(row)
            raise FlowProviderCallStateConflictError(
                f"Flow provider call {call_id} already has different completion evidence."
            )
        if row.status != ProviderCallStatus.STARTED.value:
            raise FlowProviderCallStateConflictError(
                f"Flow provider call {call_id} is already terminal as {row.status}."
            )

        row.status = ProviderCallStatus.COMPLETED.value
        row.response_model = receipt.response_model
        row.provider_response_id = receipt.provider_response_id
        row.num_tokens_input = receipt.num_tokens_input
        row.num_tokens_output = receipt.num_tokens_output
        row.input_source = receipt.input_source
        row.output_source = receipt.output_source
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(row)
        return ProviderCall.model_validate(row)

    async def reject_call(
        self,
        *,
        call_id: UUID,
        reason: ProviderCallRejectionReason,
    ) -> ProviderCall:
        return await self._finish_without_receipt(
            call_id=call_id,
            status=ProviderCallStatus.REJECTED,
            reason=ProviderCallRejectionReason(reason).value,
        )

    async def mark_outcome_unknown(
        self,
        *,
        call_id: UUID,
        reason: ProviderCallUnknownReason,
    ) -> ProviderCall:
        return await self._finish_without_receipt(
            call_id=call_id,
            status=ProviderCallStatus.OUTCOME_UNKNOWN,
            reason=ProviderCallUnknownReason(reason).value,
        )

    async def _finish_without_receipt(
        self,
        *,
        call_id: UUID,
        status: ProviderCallStatus,
        reason: str,
    ) -> ProviderCall:
        row = await self.session.scalar(
            sa.select(FlowProviderCalls)
            .where(FlowProviderCalls.id == call_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if row is None:
            raise FlowProviderCallNotFoundError(
                f"Flow provider call {call_id} was not found."
            )
        if row.status == status.value and row.outcome_reason == reason:
            return ProviderCall.model_validate(row)
        if row.status != ProviderCallStatus.STARTED.value:
            raise FlowProviderCallStateConflictError(
                f"Flow provider call {call_id} is already terminal as {row.status}."
            )

        row.status = status.value
        row.outcome_reason = reason
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(row)
        return ProviderCall.model_validate(row)


def _completion_matches(
    row: FlowProviderCalls,
    receipt: ProviderCallCompletion,
) -> bool:
    return (
        row.response_model == receipt.response_model
        and row.provider_response_id == receipt.provider_response_id
        and row.num_tokens_input == receipt.num_tokens_input
        and row.num_tokens_output == receipt.num_tokens_output
        and row.input_source == receipt.input_source
        and row.output_source == receipt.output_source
    )


def _to_evidence(
    *,
    call: FlowProviderCalls,
    step_id: UUID,
    step_order: int,
    attempt_no: int,
) -> ProviderCallEvidence:
    return ProviderCallEvidence.model_validate(
        {
            "event_id": call.id,
            "attempt_id": call.flow_step_attempt_id,
            "step_id": step_id,
            "step_order": step_order,
            "attempt_no": attempt_no,
            "ordinal": call.ordinal,
            "status": call.status,
            "request_schema_version": call.request_schema_version,
            "provider_request_hash": call.provider_request_hash,
            "requested_model": call.requested_model,
            "provider": call.provider,
            "response_format": call.response_format,
            "requested_capabilities": tuple(call.requested_capabilities),
            "call_reason": call.call_reason,
            "mapped_execution_mode": call.mapped_execution_mode,
            "mapped_item_index": call.mapped_item_index,
            "mapped_source_index": call.mapped_source_index,
            "mapped_source_id": call.mapped_source_id,
            "response_model": call.response_model,
            "provider_response_id": call.provider_response_id,
            "num_tokens_input": call.num_tokens_input,
            "num_tokens_output": call.num_tokens_output,
            "input_source": call.input_source,
            "output_source": call.output_source,
            "outcome_reason": call.outcome_reason,
            "requested_at": call.requested_at,
            "finished_at": call.finished_at,
        }
    )
