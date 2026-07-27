from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowProviderCalls, FlowStepAttempts
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


class FlowProviderCallAttemptNotOpenError(RuntimeError):
    pass


class FlowProviderCallNotFoundError(RuntimeError):
    pass


class FlowProviderCallStateConflictError(RuntimeError):
    pass


class FlowProviderCallRepository:
    """Owns ordered provider-call lifecycle rows under a Flow step attempt."""

    def __init__(self, session: AsyncSession):
        self.session = session

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
    ) -> ProviderCallEvidencePage:
        if limit < 1:
            raise ValueError("Provider-call evidence limit must be positive.")

        predicates = [
            FlowStepAttempts.flow_run_id == run_id,
            FlowStepAttempts.tenant_id == tenant_id,
        ]
        if attempt_id is not None:
            predicates.append(FlowStepAttempts.id == attempt_id)

        total_count = int(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowProviderCalls)
                .join(
                    FlowStepAttempts,
                    FlowStepAttempts.id == FlowProviderCalls.flow_step_attempt_id,
                )
                .where(*predicates)
            )
            or 0
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

        rows = (
            await self.session.execute(
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
                .order_by(
                    FlowStepAttempts.step_order.asc(),
                    FlowStepAttempts.attempt_no.asc(),
                    FlowProviderCalls.ordinal.asc(),
                    FlowProviderCalls.id.asc(),
                )
                .limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
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

    async def start_call(
        self,
        *,
        attempt_id: UUID,
        request: ProviderCallRequest,
    ) -> ProviderCall:
        locked_attempt_id = await self.session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.id == attempt_id)
            .where(FlowStepAttempts.status == FlowStepAttemptStatus.STARTED.value)
            .with_for_update()
        )
        if locked_attempt_id is None:
            raise FlowProviderCallAttemptNotOpenError(
                f"Flow step attempt {attempt_id} is not open for a provider call."
            )

        return await self._insert_started_call(
            attempt_id=locked_attempt_id,
            request=request,
        )

    async def start_call_for_execution(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        request: ProviderCallRequest,
    ) -> ProviderCall:
        attempt_id = await self.session.scalar(
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(FlowStepAttempts.status == FlowStepAttemptStatus.STARTED.value)
            .with_for_update()
        )
        if attempt_id is None:
            raise FlowProviderCallAttemptNotOpenError(
                "The Flow step attempt is not open for a provider call."
            )
        return await self._insert_started_call(
            attempt_id=attempt_id,
            request=request,
        )

    async def _insert_started_call(
        self,
        *,
        attempt_id: UUID,
        request: ProviderCallRequest,
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
