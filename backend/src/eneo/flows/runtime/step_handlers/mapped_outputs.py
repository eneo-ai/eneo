from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
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


def mapped_rag_metadata(
    *,
    execution_mode: str,
    collection_key: str,
    outputs: Iterable[StepExecutionOutput],
) -> dict[str, Any] | None:
    metadata = [
        output.rag_metadata for output in outputs if output.rag_metadata is not None
    ]
    if not metadata:
        return None
    return {
        "execution_mode": execution_mode,
        collection_key: metadata,
    }
