from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.runtime import (
    ProviderCallTokenReceipt,
    StepDiagnostic,
    StepExecutionOutput,
    TokenCountSource,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    MappedAdmissionProvenance,
    MappedExecutionMode,
)
from eneo.main.exceptions import TypedIOValidationException


def sum_optional_token_counts(values: Iterable[int | None]) -> int | None:
    total = 0
    observed = False
    for value in values:
        if isinstance(value, int):
            total += value
            observed = True
    return total if observed else None


def aggregate_token_source(
    outputs: Iterable[StepExecutionOutput], *, dimension: str
) -> TokenCountSource:
    sources: set[TokenCountSource] = {
        output.input_token_source
        if dimension == "input"
        else output.output_token_source
        for output in outputs
    }
    sources.discard("not_applicable")
    if not sources:
        return "not_applicable"
    return next(iter(sources)) if len(sources) == 1 else "mixed"


def mapped_provider_call_receipts(
    outputs: Iterable[StepExecutionOutput],
) -> list[ProviderCallTokenReceipt]:
    return [receipt for output in outputs for receipt in output.provider_call_receipts]


def mapped_admission_payload(
    *,
    execution_mode: MappedExecutionMode,
    estimates: list[int],
    policy: FlowMappedExecutionPolicy,
) -> MappedAdmissionProvenance:
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
