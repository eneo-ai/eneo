"""Shared structural policy for targeted underlag rewrites."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from intric.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.planning_state import AggregationIntent


TARGETED_UNDERLAG_SOFT_CAP = 6
"""Cap on TEXT-emitting prior content steps a targeted-underlag composer absorbs.

Text priors get body-coalesced through explicit previous-output refs, while JSON
priors with output contracts bind field-by-field and do not count against this
cap.
"""


@dataclass(frozen=True, slots=True)
class TargetedUnderlagStepSignal:
    input_source: InputSource
    input_type: InputType
    output_type: OutputType
    is_renderer: bool
    has_structured_json_output: bool
    already_targets_previous_fields: bool
    question_targets_prior_structured_field: bool
    is_source_surfacing_text: bool = False
    question_targets_prior_text_output_count: int = 0


_SOURCE_SURFACING_INPUT_TYPES = frozenset(
    {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
)


def is_source_surfacing_text(
    *,
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
) -> bool:
    return (
        input_source == InputSource.FLOW_INPUT
        and input_type in _SOURCE_SURFACING_INPUT_TYPES
        and output_type == OutputType.TEXT
    )


def is_document_renderer(
    *,
    output_type: OutputType,
    output_mode: OutputMode | None = None,
    document_delivery_mode: str | None = None,
) -> bool:
    return (
        output_mode == OutputMode.TEMPLATE_FILL
        or document_delivery_mode == "template_fill"
        or output_type in {OutputType.DOCX, OutputType.PDF}
    )


def last_compositional_step_index(
    steps: Sequence[TargetedUnderlagStepSignal],
) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if not steps[index].is_renderer:
            return index
    return None


def targeted_underlag_rewrite_indexes(
    steps: Sequence[TargetedUnderlagStepSignal],
    *,
    aggregation_intent: "AggregationIntent",
) -> tuple[int, ...]:
    if aggregation_intent == "compare":
        return ()

    indexes: list[int] = []
    for index, step in enumerate(steps):
        if index == 0 or step.is_renderer:
            continue
        if step.input_source != InputSource.ALL_PREVIOUS_STEPS:
            continue
        if step.input_type != InputType.TEXT or step.output_type != OutputType.TEXT:
            continue
        if (
            step.already_targets_previous_fields
            or step.question_targets_prior_structured_field
        ):
            continue

        priors = [prior for prior in steps[:index] if not prior.is_renderer]
        if not priors:
            continue
        text_priors_count = sum(
            1 for prior in priors if prior.output_type == OutputType.TEXT
        )
        if text_priors_count > TARGETED_UNDERLAG_SOFT_CAP:
            continue
        if any(prior.has_structured_json_output for prior in priors):
            indexes.append(index)

    return tuple(indexes)


def final_assembler_rewrite_indexes(
    steps: Sequence[TargetedUnderlagStepSignal],
    *,
    aggregation_intent: "AggregationIntent",
) -> tuple[int, ...]:
    if aggregation_intent == "compare":
        return ()

    last_renderer_index = _last_renderer_index(steps)
    if last_renderer_index is None:
        return ()

    indexes: list[int] = []
    for composer_index, composer in enumerate(steps[:last_renderer_index]):
        if composer_index == 0:
            continue
        if composer.is_renderer:
            continue
        if composer.input_source != InputSource.ALL_PREVIOUS_STEPS:
            continue
        if (
            composer.input_type != InputType.TEXT
            or composer.output_type != OutputType.TEXT
        ):
            continue

        prior_text_count = sum(
            1
            for prior in steps[:composer_index]
            if not prior.is_renderer
            and prior.output_type == OutputType.TEXT
            and not prior.is_source_surfacing_text
        )
        if prior_text_count < 2:
            continue
        if composer.question_targets_prior_text_output_count >= prior_text_count:
            continue
        indexes.append(composer_index)

    return tuple(indexes)


def _last_renderer_index(steps: Sequence[TargetedUnderlagStepSignal]) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if steps[index].is_renderer:
            return index
    return None


def terminal_renderer_rewrite_indexes(
    steps: Sequence[TargetedUnderlagStepSignal],
) -> tuple[int, ...]:
    """Terminal document renderers should render the composed text body only."""
    indexes: list[int] = []
    for index, step in enumerate(steps):
        if index != len(steps) - 1:
            continue
        if not step.is_renderer:
            continue
        if step.input_source != InputSource.ALL_PREVIOUS_STEPS:
            continue
        if step.input_type != InputType.TEXT:
            continue

        composer_index = last_compositional_step_index(steps[:index])
        if composer_index is None:
            continue
        composer = steps[composer_index]
        if composer.output_type != OutputType.TEXT:
            continue
        if composer.is_source_surfacing_text:
            continue
        indexes.append(index)

    return tuple(indexes)
