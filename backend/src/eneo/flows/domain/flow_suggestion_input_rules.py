"""Suggestions about what reaches a step's model: more than it needs.

``broad_all_previous_steps``, ``whole_structured_read``,
``per_item_prompt_read`` and ``repeated_long_material``. Each judges the
reads ``DraftReads`` holds, never a template of its own. None is a patch:
choosing what a step needs takes judgement or a change of structure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import ValidationError

from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    SuggestionStep,
    describe_read,
    join_descriptions,
    make_suggestion,
    read_payload,
    uses_completion_model,
)
from eneo.flows.domain.long_material import long_material_config
from eneo.flows.domain.step_mapped_execution import (
    FlowStepMappedExecutionConfigurationError,
    FlowStepMappedExecutionMode,
    resolve_step_mapped_execution,
)
from eneo.flows.enums import FlowInputSource, FlowOutputType
from eneo.flows.input_binding_contract_rules import has_explicit_underlag
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    STRUCTURED_SELECTOR_HEAD,
    StepRead,
)
from eneo.main.exceptions import BadRequestException

# `all_previous_steps` with at least this many earlier steps is broad.
BROAD_ALL_PREVIOUS_MIN_STEPS = 3
# A whole read of a JSON step whose contract has at least this many
# top-level fields is worth narrowing to the fields the step needs.
WHOLE_STRUCTURED_MIN_FIELDS = 4

_WHOLE_SELECTORS = ((), (STRUCTURED_SELECTOR_HEAD,))


def broad_all_previous_steps(draft: DraftReads) -> list[FlowSuggestion]:
    """``broad_all_previous_steps``: a model step that takes every earlier
    step as its input, where one of them is derived from another it also
    gets (``medium``: the same material twice in two forms), or that gets
    ``BROAD_ALL_PREVIOUS_MIN_STEPS`` or more of them (``low``). An earlier
    step is derived from another when its own input or prompt reads it.
    ``params["suggested_source_refs"]`` lists the earlier steps the step's
    prompt does not already read, for the chat to propose as source refs."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if (
            not uses_completion_model(step)
            or FlowInputSource(step.input_source)
            is not FlowInputSource.ALL_PREVIOUS_STEPS
        ):
            continue
        reads = draft.model_reads(step)
        earlier = [
            read.step_order for read in reads if read.site == INPUT_SOURCE_READ_SITE
        ]
        if not earlier:
            # Underlag replaces the implicit input.
            continue
        got = set(earlier)
        derived = sorted(
            (later, source)
            for later in got
            if (later_step := draft.step_at(later)) is not None
            for source in {read.step_order for read in draft.model_reads(later_step)}
            if source in got
        )
        broad = len(earlier) >= BROAD_ALL_PREVIOUS_MIN_STEPS
        if not derived and not broad:
            continue
        prompt_orders = {read.step_order for read in reads if read.channel == "prompt"}
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS,
                steps=(step.id,),
                premise={
                    "derived": [list(pair) for pair in derived],
                    "broad": broad,
                },
                params={
                    "earlier_step_count": len(earlier),
                    "derived": [
                        {"step_order": later, "from_step_order": source}
                        for later, source in derived
                    ],
                    "suggested_source_refs": [
                        _step_payload(draft, order)
                        for order in earlier
                        if order not in prompt_orders
                    ],
                },
                message=_broad_message(step, len(earlier), derived),
                level="medium" if derived else "low",
                fix=FlowSuggestionFix(kind="assisted"),
            )
        )
    return suggestions


def _broad_message(
    step: SuggestionStep, earlier: int, derived: Sequence[tuple[int, int]]
) -> str:
    if derived:
        later, source = derived[0]
        return (
            f"Step {step.step_order} takes all {earlier} earlier steps as its "
            f"input, among them step {later}, which is derived from step "
            f"{source}, so its model receives that material twice in two forms."
        )
    return (
        f"Step {step.step_order} takes all {earlier} earlier steps as its "
        "input; naming the results it needs as source references sends only "
        "those."
    )


def whole_structured_reads(draft: DraftReads) -> list[FlowSuggestion]:
    """``whole_structured_read``: a model step reads the whole text or the
    whole structured value of a JSON step whose output contract has
    ``WHOLE_STRUCTURED_MIN_FIELDS`` or more top-level fields, so the chat can
    propose the fields it needs by ``field_path``. Not judged: the reads of
    ``all_previous_steps`` (``broad_all_previous_steps`` covers them) and the
    input of a step mapped over the items of what it reads."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        if not uses_completion_model(step):
            continue
        mapped = mapped_mode(step) is not None
        by_producer: dict[int, list[StepRead]] = {}
        for read in draft.model_reads(step):
            if read.selector not in _WHOLE_SELECTORS:
                continue
            if read.site == INPUT_SOURCE_READ_SITE and (
                mapped
                or FlowInputSource(step.input_source)
                is FlowInputSource.ALL_PREVIOUS_STEPS
            ):
                continue
            by_producer.setdefault(read.step_order, []).append(read)
        for producer_order, reads in sorted(by_producer.items()):
            producer = draft.step_at(producer_order)
            fields = contract_fields(producer) if producer is not None else ()
            if producer is None or len(fields) < WHOLE_STRUCTURED_MIN_FIELDS:
                continue
            described = join_descriptions([describe_read(read, step) for read in reads])
            suggestions.append(
                make_suggestion(
                    FlowSuggestionCode.WHOLE_STRUCTURED_READ,
                    steps=(step.id, producer.id),
                    premise={
                        "producer_step_order": producer_order,
                        "sites": [
                            {"channel": read.channel, "site": read.site}
                            for read in reads
                        ],
                    },
                    params={
                        "producer_step_order": producer_order,
                        "producer_step_id": str(producer.id),
                        "fields": list(fields),
                        "reads": [read_payload(read) for read in reads],
                    },
                    message=(
                        f"Step {step.step_order} reads all of step "
                        f"{producer_order}'s {len(fields)} fields {described}; "
                        "reading only the fields it needs sends less to its model."
                    ),
                    level="low",
                    fix=FlowSuggestionFix(kind="assisted"),
                )
            )
    return suggestions


def per_item_prompt_reads(draft: DraftReads) -> list[FlowSuggestion]:
    """``per_item_prompt_read``: a mapped step (``per_source`` runtime
    input, or ``item_map``) whose prompt interpolates a whole earlier result,
    which is then sent once per item."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        mode = mapped_mode(step)
        if mode is None or not uses_completion_model(step):
            continue
        by_producer: dict[int, list[StepRead]] = {}
        for read in draft.model_reads(step):
            if read.channel == "prompt" and read.selector in _WHOLE_SELECTORS:
                by_producer.setdefault(read.step_order, []).append(read)
        for producer_order, reads in sorted(by_producer.items()):
            producer = draft.step_at(producer_order)
            suggestions.append(
                make_suggestion(
                    FlowSuggestionCode.PER_ITEM_PROMPT_READ,
                    steps=(step.id, *((producer.id,) if producer is not None else ())),
                    premise={
                        "producer_step_order": producer_order,
                        "execution_mode": mode,
                        "sites": [read.site for read in reads],
                    },
                    params={
                        "execution_mode": mode,
                        "producer_step_order": producer_order,
                        "producer_step_id": (
                            str(producer.id) if producer is not None else None
                        ),
                        "reads": [read_payload(read) for read in reads],
                    },
                    message=(
                        f"Step {step.step_order} runs once per item and its "
                        f"prompt holds the whole result of step {producer_order}, "
                        "so that result is sent again for every item."
                    ),
                    level="high",
                    fix=FlowSuggestionFix(kind="advice"),
                )
            )
    return suggestions


def repeated_long_material(draft: DraftReads) -> list[FlowSuggestion]:
    """``repeated_long_material``: two or more steps digest the same source
    with ``input_config.long_material``: their inputs read the same earlier
    step, or both take the run input. Reported on each later step, naming
    the first earlier one that shares a source."""

    digesting: list[tuple[SuggestionStep, frozenset[int], bool]] = []
    for step in draft.steps:
        if not _digests_long_material(step):
            continue
        orders = frozenset(
            read.step_order
            for read in draft.reads[step.step_order]
            if read.channel == "input"
        )
        run_input = FlowInputSource(
            step.input_source
        ) is FlowInputSource.FLOW_INPUT and not has_explicit_underlag(
            step.input_bindings
        )
        digesting.append((step, orders, run_input))
    suggestions: list[FlowSuggestion] = []
    for index, (step, orders, run_input) in enumerate(digesting):
        for earlier, earlier_orders, earlier_run_input in digesting[:index]:
            shared = sorted(orders & earlier_orders)
            shares_run_input = run_input and earlier_run_input
            if not shared and not shares_run_input:
                continue
            what = join_descriptions(
                [f"step {order}" for order in shared]
                + (["the run input"] if shares_run_input else [])
            )
            suggestions.append(
                make_suggestion(
                    FlowSuggestionCode.REPEATED_LONG_MATERIAL,
                    steps=(step.id, earlier.id),
                    premise={
                        "shared_step_orders": shared,
                        "shares_run_input": shares_run_input,
                    },
                    params={
                        "earlier_step_order": earlier.step_order,
                        "earlier_step_id": str(earlier.id),
                        "shared_step_orders": shared,
                        "shares_run_input": shares_run_input,
                    },
                    message=(
                        f"Steps {earlier.step_order} and {step.step_order} both "
                        f"digest {what} as long material; one digest step that "
                        "both read does that work once, when they need the "
                        "same facts."
                    ),
                    level="medium",
                    fix=FlowSuggestionFix(kind="advice"),
                )
            )
            break
    return suggestions


def mapped_mode(step: SuggestionStep) -> FlowStepMappedExecutionMode | None:
    """The mapped mode the runtime dispatches the step in, None when it runs
    once (or its mapping cannot run, which publish reports)."""
    try:
        mapped = resolve_step_mapped_execution(
            input_source=FlowInputSource(step.input_source).value,
            input_type=str(getattr(step.input_type, "value", step.input_type)),
            output_mode=str(getattr(step.output_mode, "value", step.output_mode)),
            output_type=str(getattr(step.output_type, "value", step.output_type)),
            input_config=cast(dict[str, Any] | None, step.input_config),
        )
    except (FlowStepMappedExecutionConfigurationError, BadRequestException, ValueError):
        return None
    return mapped.execution_mode if mapped is not None else None


def _digests_long_material(step: SuggestionStep) -> bool:
    try:
        return (
            long_material_config(cast(dict[str, Any] | None, step.input_config))
            is not None
        )
    except ValidationError:
        return False


def contract_fields(step: SuggestionStep) -> tuple[str, ...]:
    """The top-level fields of a JSON step's output contract, in its order."""
    if FlowOutputType(step.output_type) is not FlowOutputType.JSON:
        return ()
    properties = (step.output_contract or {}).get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(str(name) for name in cast(Mapping[str, object], properties))


def _step_payload(draft: DraftReads, order: int) -> dict[str, object]:
    step = draft.step_at(order)
    return {"step_order": order, "step_id": str(step.id) if step is not None else None}


__all__ = [
    "BROAD_ALL_PREVIOUS_MIN_STEPS",
    "WHOLE_STRUCTURED_MIN_FIELDS",
    "broad_all_previous_steps",
    "contract_fields",
    "mapped_mode",
    "per_item_prompt_reads",
    "repeated_long_material",
    "whole_structured_reads",
]
