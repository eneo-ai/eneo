"""Evidence a failing step hands to the attempt writer on its error.

A step that fails still owes its attempt record what it did first: what
retrieval read, how many mapped items completed, the output it rejected. The
runtime and the step handlers attach that to the error here, and the executor
reads it back here, so the record has one typed shape instead of loose
attributes on the exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eneo.flows.domain.step_output import RejectedOutput, StepOutputAbortedException

_ATTRIBUTE = "_eneo_step_failure_evidence"


@dataclass(frozen=True, slots=True)
class StepFailureEvidence:
    rag_metadata: dict[str, Any] | None = None
    completed_items: int | None = None
    total_items: int | None = None
    rejected_output: str | RejectedOutput | None = None


_NONE = StepFailureEvidence()


def failure_evidence(exc: BaseException | None) -> StepFailureEvidence:
    """What ``exc`` itself carries (not its cause); empty when nothing was attached."""
    evidence = getattr(exc, _ATTRIBUTE, None)
    return evidence if isinstance(evidence, StepFailureEvidence) else _NONE


def attach_failure_evidence(
    exc: BaseException,
    *,
    rag_metadata: dict[str, Any] | None = None,
    completed_items: int | None = None,
    total_items: int | None = None,
    rejected_output: str | RejectedOutput | None = None,
) -> None:
    """Set the given fields on ``exc``; a field passed as ``None`` keeps its value."""
    current = failure_evidence(exc)
    setattr(
        exc,
        _ATTRIBUTE,
        StepFailureEvidence(
            rag_metadata=current.rag_metadata if rag_metadata is None else rag_metadata,
            completed_items=(
                current.completed_items if completed_items is None else completed_items
            ),
            total_items=current.total_items if total_items is None else total_items,
            rejected_output=(
                current.rejected_output if rejected_output is None else rejected_output
            ),
        ),
    )


def rejected_output_of(exc: BaseException) -> str | RejectedOutput | None:
    """An aborted response's own sample wins over output attached later."""
    if isinstance(exc, StepOutputAbortedException) and exc.rejected_output is not None:
        return exc.rejected_output
    return failure_evidence(exc).rejected_output
