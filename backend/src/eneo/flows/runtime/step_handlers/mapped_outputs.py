from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from eneo.flows.runtime.models import StepDiagnostic, StepExecutionOutput


def sum_optional_token_counts(values: Iterable[int | None]) -> int | None:
    total = 0
    observed = False
    for value in values:
        if isinstance(value, int):
            total += value
            observed = True
    return total if observed else None


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
