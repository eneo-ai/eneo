from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from eneo.main.exceptions import BadRequestException


def _classification_level(classification: Any) -> int | None:
    if classification is None:
        return None
    level = getattr(classification, "security_level", None)
    return level if isinstance(level, int) else None


def _max_level(*levels: int | None) -> int | None:
    present = [level for level in levels if level is not None]
    return max(present) if present else None


def _knowledge_level(assistant: Any) -> int | None:
    levels: list[int] = []
    for item in (
        list(getattr(assistant, "collections", []) or [])
        + list(getattr(assistant, "websites", []) or [])
        + list(getattr(assistant, "integration_knowledge_list", []) or [])
    ):
        embedding_model = getattr(item, "embedding_model", None)
        level = _classification_level(
            getattr(embedding_model, "security_classification", None)
        )
        if level is not None:
            levels.append(level)
    return max(levels) if levels else None


def _input_floor_level(
    *,
    step_order: int,
    input_source: str,
    prior_output_levels_by_order: dict[int, int | None],
    baseline_level: int | None,
) -> int | None:
    if input_source == "previous_step":
        return _max_level(
            baseline_level,
            prior_output_levels_by_order.get(step_order - 1),
        )
    if input_source == "all_previous_steps":
        prior_levels = [
            level
            for order, level in prior_output_levels_by_order.items()
            if order < step_order and level is not None
        ]
        return _max_level(baseline_level, max(prior_levels) if prior_levels else None)
    return baseline_level


@dataclass(frozen=True)
class FlowStepClassificationEvaluation:
    required_model_level: int | None
    effective_output_level: int | None


def evaluate_step_security_classification(
    *,
    step_order: int,
    input_source: str,
    output_classification_override: int | None,
    prior_output_levels_by_order: dict[int, int | None],
    assistant: Any,
    space: Any,
) -> FlowStepClassificationEvaluation:
    baseline_level = _classification_level(
        getattr(space, "security_classification", None)
    )
    input_floor_level = _input_floor_level(
        step_order=step_order,
        input_source=input_source,
        prior_output_levels_by_order=prior_output_levels_by_order,
        baseline_level=baseline_level,
    )
    knowledge_level = _knowledge_level(assistant)
    model_level = _classification_level(
        getattr(
            getattr(assistant, "completion_model", None),
            "security_classification",
            None,
        )
    )

    required_model_level = _max_level(input_floor_level, knowledge_level)
    if required_model_level is not None and (
        model_level is None or model_level < required_model_level
    ):
        raise BadRequestException(
            f"Step {step_order}: assistant model does not meet the required security classification.",
            code="flow_step_security_classification_mismatch",
        )

    base_output_level = _max_level(input_floor_level, knowledge_level)
    if (
        output_classification_override is not None
        and base_output_level is not None
        and output_classification_override < base_output_level
    ):
        raise BadRequestException(
            f"Step {step_order}: output classification override would lower the effective classification of the step output.",
            code="flow_step_output_classification_write_down",
        )

    return FlowStepClassificationEvaluation(
        required_model_level=required_model_level,
        effective_output_level=_max_level(
            base_output_level, output_classification_override
        ),
    )


def evidence_classification_level(
    step_output_levels: Mapping[int, int | None],
) -> int:
    """The level a reader of this run's evidence must clear.

    The highest effective output level across the run's steps, 0 when nothing
    in the run is classified. Recorded on the run when it starts, so that a
    later reader (a person, an export, the AI builder's review) is held to the
    rule that applied when the evidence was produced rather than to whatever
    the flow or space says at reading time. A run recorded before this rule
    carries no level, and readers treat that as unknown, not as 0.
    """
    return max(
        (level for level in step_output_levels.values() if level is not None),
        default=0,
    )
