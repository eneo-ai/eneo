from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.rag_evidence import (
    MAPPED_CALLS_COMPLETE_KEY,
    MAPPED_EXECUTION_MODE_KEY,
    RetrievedKnowledgeEvidence,
    recompute_mapped_aggregates,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import StepDiagnostic, StepExecutionOutput
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    MappedAdmissionProvenance,
    MappedExecutionMode,
)
from eneo.main.exceptions import TypedIOValidationException


def mapped_admission_payload(
    *,
    execution_mode: MappedExecutionMode,
    estimates: list[int],
    native_json_fallback_possible: bool,
    policy: FlowMappedExecutionPolicy,
) -> MappedAdmissionProvenance:
    provider_call_upper_bound = len(estimates) + int(native_json_fallback_possible)
    call_ceiling = policy.max_provider_calls_per_mapped_step
    if call_ceiling is not None and provider_call_upper_bound > call_ceiling:
        raise TypedIOValidationException(
            f"Mapped step may require up to {provider_call_upper_bound} provider "
            f"calls, exceeding the organization ceiling of {call_ceiling} calls.",
            code=FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED.value,
        )
    # This token policy measures logical mapped packages; the separate call
    # ceiling reserves the capability-rejection fallback attempt.
    total = sum(estimates)
    ceiling = policy.max_estimated_input_tokens_per_mapped_step
    if ceiling is not None and total > ceiling:
        raise TypedIOValidationException(
            f"Mapped step base packages use about {total} input tokens, exceeding "
            f"the organization ceiling of {ceiling} tokens.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        )
    return MappedAdmissionProvenance(
        version=policy.version,
        execution_mode=execution_mode,
        prospective_provider_calls=len(estimates),
        estimated_input_tokens=total,
        per_call_estimated_input_tokens=tuple(estimates),
        max_estimated_input_tokens=ceiling,
        policy_source="configured" if ceiling is not None else "unset",
        knowledge_included=False,
    )


def mapped_output_diagnostics(
    outputs: Iterable[StepExecutionOutput],
) -> tuple[StepDiagnostic, ...]:
    return tuple(diagnostic for output in outputs for diagnostic in output.diagnostics)


class MappedPassageBudget:
    """One passage-byte budget shared by every call of a mapped step.

    A call is admitted as soon as it completes, so passage text the step cannot
    afford is released before the next call runs. Bounding only the assembled
    result would let a mapped step hold every call's full evidence at once.

    Admission rewrites the call's evidence through the canonical aggregate, so a
    call's counters are recomputed from the passages it actually kept and cannot
    drift from them.
    """

    def __init__(self, *, policy: FlowRagEvidencePolicy) -> None:
        self._remaining = policy.max_recorded_passage_bytes_per_step

    def admit(self, rag_metadata: dict[str, Any] | None) -> None:
        if not isinstance(rag_metadata, dict):
            return
        evidence = RetrievedKnowledgeEvidence.from_payload(rag_metadata)
        if not evidence.sources:
            return
        bounded = evidence.release_passages_beyond(self._remaining)
        self._remaining = max(0, self._remaining - bounded.recorded_passage_bytes)
        bounded.write_into(rag_metadata)


class MappedCallEvidence:
    """Retrieval evidence for a mapped step, assembled as its calls complete.

    A mapped step that fails partway must still record what its completed calls
    retrieved: the calls really happened, and a run that hides them would report
    a step as having retrieved nothing. The collector therefore holds the
    admitted per-call payloads, so a failure can publish a partial envelope
    rather than discarding the evidence with the local call list.
    """

    def __init__(
        self,
        *,
        policy: FlowRagEvidencePolicy,
        execution_mode: str,
        collection_key: str,
    ) -> None:
        self._budget = MappedPassageBudget(policy=policy)
        self._execution_mode = execution_mode
        self._collection_key = collection_key
        self._calls: list[dict[str, Any]] = []

    def admit(self, rag_metadata: dict[str, Any] | None) -> None:
        """Bound a completed call's evidence and keep it for the envelope."""
        if not isinstance(rag_metadata, dict):
            return
        self._budget.admit(rag_metadata)
        if not any(call is rag_metadata for call in self._calls):
            self._calls.append(rag_metadata)

    def payload(self) -> dict[str, Any] | None:
        return self._build(complete=True)

    def partial_payload(self) -> dict[str, Any] | None:
        return self._build(complete=False)

    def _build(self, *, complete: bool) -> dict[str, Any] | None:
        if not self._calls:
            return None
        envelope: dict[str, Any] = {
            MAPPED_EXECUTION_MODE_KEY: self._execution_mode,
            MAPPED_CALLS_COMPLETE_KEY: complete,
            self._collection_key: self._calls,
        }
        return recompute_mapped_aggregates(envelope)


def carry_call_evidence(exc: BaseException, rag_metadata: object) -> None:
    """Attach retrieval evidence to an error so the attempt writer records it.

    Used where a call has already retrieved and then fails — including output
    validation that runs after the call itself succeeded.
    """
    if isinstance(rag_metadata, dict) and getattr(exc, "rag_metadata", None) is None:
        setattr(exc, "rag_metadata", rag_metadata)
