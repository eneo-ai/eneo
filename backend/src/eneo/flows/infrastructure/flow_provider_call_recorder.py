from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from sqlalchemy.exc import OperationalError

from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallObserverError,
    ProviderCallRequestFacts,
    ProviderCallResultFacts,
)
from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallRejectionReason as ObservedRejectionReason,
)
from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallUnknownReason as ObservedUnknownReason,
)
from eneo.database.database import sessionmanager
from eneo.flows.domain.provider_call import (
    ProviderCall,
    ProviderCallCompletion,
    ProviderCallReason,
    ProviderCallRejectionReason,
    ProviderCallRequest,
    ProviderCallRequestedCapability,
    ProviderCallResponseFormat,
    ProviderCallUnknownReason,
)
from eneo.flows.domain.provider_call_evidence_gap import ProviderCallEvidenceGap
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdgeIndexes,
    MappedProviderCallProvenance,
)
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)

_PERSISTENCE_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.2)
_TRANSIENT_SQLSTATES = frozenset(
    {
        "40001",  # serialization_failure
        "40P01",  # deadlock_detected
        "57P01",  # admin_shutdown
        "57P02",  # crash_shutdown
        "57P03",  # cannot_connect_now
    }
)

_T = TypeVar("_T")


class ProviderCallEvidencePersistenceError(ProviderCallObserverError):
    def __init__(self, *, facts: ProviderCallEvidenceGap):
        super().__init__(
            "The provider-call outcome could not be persisted after bounded retries."
        )
        self.facts = facts


class FlowProviderCallRecorder:
    """Persists one Flow provider call through isolated short transactions."""

    def __init__(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        mapped_call: MappedProviderCallProvenance | None,
        resolved_input_edge_indexes: FlowResolvedInputEdgeIndexes,
    ):
        self.run_id = run_id
        self.step_id = step_id
        self.attempt_no = attempt_no
        self.tenant_id = tenant_id
        self.mapped_call = mapped_call
        self.resolved_input_edge_indexes = resolved_input_edge_indexes
        self._started_evidence: dict[UUID, tuple[int, str]] = {}

    async def started(self, request: ProviderCallRequestFacts) -> UUID:
        async def persist() -> ProviderCall:
            async with sessionmanager.session() as session, session.begin():
                return await FlowProviderCallRepository(
                    session
                ).start_call_for_execution(
                    run_id=self.run_id,
                    step_id=self.step_id,
                    attempt_no=self.attempt_no,
                    tenant_id=self.tenant_id,
                    request=ProviderCallRequest(
                        request_schema_version=request.request_schema_version,
                        provider_request_hash=request.provider_request_hash,
                        requested_model=request.requested_model,
                        provider=request.provider,
                        response_format=ProviderCallResponseFormat(
                            request.response_format
                        ),
                        requested_capabilities=tuple(
                            ProviderCallRequestedCapability(capability)
                            for capability in request.requested_capabilities
                        ),
                        call_reason=_flow_call_reason(request.reason),
                        mapped_call=self.mapped_call,
                    ),
                    resolved_input_edge_indexes=self.resolved_input_edge_indexes,
                )

        started = await self._persist_with_retry(
            operation=persist,
            facts=ProviderCallEvidenceGap(
                call_id=None,
                ordinal=None,
                provider_request_hash=request.provider_request_hash,
                provider_response_id=None,
                outcome="started",
            ),
        )
        self._started_evidence[started.id] = (
            started.ordinal,
            request.provider_request_hash,
        )
        return started.id

    async def completed(
        self,
        call_id: UUID,
        result: ProviderCallResultFacts,
    ) -> None:
        receipt = ProviderCallCompletion(
            response_model=result.response_model,
            provider_response_id=result.provider_response_id,
            num_tokens_input=result.num_tokens_input,
            num_tokens_output=result.num_tokens_output,
            input_source=(
                "provider" if result.num_tokens_input is not None else "not_reported"
            ),
            output_source=(
                "provider" if result.num_tokens_output is not None else "not_reported"
            ),
        )

        async def persist() -> None:
            async with sessionmanager.session() as session, session.begin():
                await FlowProviderCallRepository(session).complete_call(
                    call_id=call_id,
                    receipt=receipt,
                )

        await self._persist_with_retry(
            operation=persist,
            facts=self._evidence_gap(
                call_id,
                provider_response_id=result.provider_response_id,
                outcome="completed",
                num_tokens_input=result.num_tokens_input,
                num_tokens_output=result.num_tokens_output,
            ),
        )

    async def rejected(
        self,
        call_id: UUID,
        reason: ObservedRejectionReason,
    ) -> None:
        async def persist() -> None:
            async with sessionmanager.session() as session, session.begin():
                await FlowProviderCallRepository(session).reject_call(
                    call_id=call_id,
                    reason=ProviderCallRejectionReason(reason),
                )

        await self._persist_with_retry(
            operation=persist,
            facts=self._evidence_gap(
                call_id,
                provider_response_id=None,
                outcome=reason,
            ),
        )

    async def outcome_unknown(
        self,
        call_id: UUID,
        reason: ObservedUnknownReason,
    ) -> None:
        async def persist() -> None:
            async with sessionmanager.session() as session, session.begin():
                await FlowProviderCallRepository(session).mark_outcome_unknown(
                    call_id=call_id,
                    reason=ProviderCallUnknownReason(reason),
                )

        await self._persist_with_retry(
            operation=persist,
            facts=self._evidence_gap(
                call_id,
                provider_response_id=None,
                outcome=reason,
            ),
        )

    def _evidence_gap(
        self,
        call_id: UUID,
        *,
        provider_response_id: str | None,
        outcome: str,
        num_tokens_input: int | None = None,
        num_tokens_output: int | None = None,
    ) -> ProviderCallEvidenceGap:
        started = self._started_evidence.get(call_id)
        return ProviderCallEvidenceGap.model_validate(
            {
                "call_id": call_id,
                "ordinal": started[0] if started is not None else None,
                "provider_request_hash": started[1] if started is not None else None,
                "provider_response_id": provider_response_id,
                "outcome": outcome,
                "num_tokens_input": num_tokens_input,
                "num_tokens_output": num_tokens_output,
            }
        )

    @staticmethod
    async def _persist_with_retry(
        *,
        operation: Callable[[], Awaitable[_T]],
        facts: ProviderCallEvidenceGap,
    ) -> _T:
        for attempt_index, delay_seconds in enumerate(
            _PERSISTENCE_RETRY_DELAYS_SECONDS
        ):
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            try:
                return await operation()
            except OperationalError as exc:
                if not _is_transient_operational_error(exc):
                    raise ProviderCallEvidencePersistenceError(facts=facts) from exc
                if attempt_index == len(_PERSISTENCE_RETRY_DELAYS_SECONDS) - 1:
                    raise ProviderCallEvidencePersistenceError(facts=facts) from exc
            except Exception as exc:
                raise ProviderCallEvidencePersistenceError(facts=facts) from exc
        raise AssertionError("Provider-call persistence retry loop did not return.")


def _flow_call_reason(reason: str) -> ProviderCallReason:
    if reason == "capability_fallback":
        return ProviderCallReason.RESPONSE_FORMAT_FALLBACK
    return ProviderCallReason(reason)


def _is_transient_operational_error(exc: OperationalError) -> bool:
    if exc.connection_invalidated:
        return True
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return isinstance(sqlstate, str) and (
        sqlstate.startswith("08") or sqlstate in _TRANSIENT_SQLSTATES
    )
