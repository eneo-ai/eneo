"""Suggestions about a draft flow: where it moves the same data twice,
carries data nobody reads, or relays a result another step could read.

Pure functions over the draft. A suggestion states what the definition
proves, never blocks publishing and changes nothing by itself. The reads it
judges are the ones ``step_lineage`` resolves for publish and the runtime,
so there is one interpretation of what a step reads. The object and the
analyzer's view of the draft are in ``flow_suggestion_model``; the rules
beyond ``duplicate_read`` in ``flow_suggestion_input_rules`` (what reaches a
model) and ``flow_suggestion_unused_rules`` (what nobody reads); the fixes in
``flow_suggestion_patches``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from eneo.flows.domain.flow_suggestion_input_rules import (
    broad_all_previous_steps,
    per_item_prompt_reads,
    repeated_long_material,
    whole_structured_reads,
)
from eneo.flows.domain.flow_suggestion_model import (
    LEVEL_RANK,
    MAX_FLOW_SUGGESTIONS,
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    FlowSuggestionFixKind,
    FlowSuggestionImpact,
    FlowSuggestionImpactBasis,
    FlowSuggestionLevel,
    SuggestionFlow,
    SuggestionStep,
    describe_read,
    join_descriptions,
    make_suggestion,
    read_payload,
    read_premises,
    suggestion_fingerprint,
    uses_completion_model,
)
from eneo.flows.domain.flow_suggestion_patches import remove_reads_patch
from eneo.flows.domain.flow_suggestion_unused_rules import (
    relay_steps,
    unread_contract_fields,
    unread_results,
    unused_form_fields,
)
from eneo.flows.enums import FlowInputSource
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    STRUCTURED_SELECTOR_HEAD,
    StepRead,
)

_RULES: tuple[Callable[[DraftReads], list[FlowSuggestion]], ...] = (
    lambda draft: [
        suggestion
        for step in draft.steps
        for suggestion in _duplicate_reads(draft, step)
    ],
    broad_all_previous_steps,
    whole_structured_reads,
    unread_contract_fields,
    unread_results,
    relay_steps,
    per_item_prompt_reads,
    repeated_long_material,
    unused_form_fields,
)
# A suggestion about no step (the run form) sorts after those of its level
# that are about a step.
_NO_STEP_ORDER = 1 << 30


def analyze_flow(flow: SuggestionFlow) -> tuple[FlowSuggestion, ...]:
    """Every suggestion the draft proves, ordered by impact level (high,
    medium, low), then the order of the step it is about, then fingerprint,
    at most ``MAX_FLOW_SUGGESTIONS``."""

    draft = DraftReads.of(flow)
    order_by_id = {step.id: step.step_order for step in draft.steps}
    suggestions = [suggestion for rule in _RULES for suggestion in rule(draft)]
    suggestions.sort(
        key=lambda suggestion: (
            LEVEL_RANK[suggestion.impact.level],
            order_by_id.get(suggestion.steps[0], _NO_STEP_ORDER)
            if suggestion.steps
            else _NO_STEP_ORDER,
            suggestion.fingerprint,
        )
    )
    return tuple(suggestions[:MAX_FLOW_SUGGESTIONS])


def _duplicate_reads(draft: DraftReads, step: SuggestionStep) -> list[FlowSuggestion]:
    """``duplicate_read``: the same earlier step reaches the step's model
    twice, through its input and its prompt or twice in one of them.

    Two reads of the same selector (the whole text twice, one field twice)
    are a duplicate. A whole read next to a narrower read of the same result
    (the text and a field of it, the structured value and a path in it) is
    reported as contained: the narrower read adds nothing the whole does not
    carry. ``params["redundant_reads"]`` names, by index into ``reads``, the
    reads a fix removes: a repeated read, and every read a wider one
    contains, never the whole read. The fix is a patch when every redundant
    read can be removed on its own (``remove_reads_patch``). Steps without a
    completion model read nothing into a model.
    """
    if not uses_completion_model(step):
        return []
    by_producer: dict[int, list[StepRead]] = defaultdict(list)
    for read in draft.model_reads(step):
        by_producer[read.step_order].append(read)
    suggestions: list[FlowSuggestion] = []
    for producer_order in sorted(by_producer):
        group = by_producer[producer_order]
        redundant = _redundant_reads(group)
        if not redundant:
            continue
        exact = any(_repeats_earlier(group, index) for index in redundant)
        contained = not exact
        if contained:
            level: FlowSuggestionLevel = "low"
        elif any(
            read.site == INPUT_SOURCE_READ_SITE
            and FlowInputSource(step.input_source) is FlowInputSource.ALL_PREVIOUS_STEPS
            for read in group
        ):
            level = "medium"
        else:
            level = "high"
        patch = remove_reads_patch(
            step,
            [group[index] for index in redundant],
            step_ref_mapping=draft.step_ref_mapping,
        )
        producer = draft.step_at(producer_order)
        step_ids = (step.id, *((producer.id,) if producer is not None else ()))
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.DUPLICATE_READ,
                steps=step_ids,
                premise={
                    "producer": draft.producer_key(producer_order),
                    "reads": read_premises(group),
                },
                params={
                    "producer_step_order": producer_order,
                    "producer_step_id": (
                        str(producer.id) if producer is not None else None
                    ),
                    "contained": contained,
                    "redundant_reads": redundant,
                    "reads": [read_payload(read) for read in group],
                },
                message=_duplicate_read_message(
                    step, producer_order, group, contained=contained
                ),
                level=level,
                fix=(
                    FlowSuggestionFix(kind="patch", patch=patch)
                    if patch is not None
                    else FlowSuggestionFix(kind="assisted")
                ),
            )
        )
    return suggestions


def _redundant_reads(group: Sequence[StepRead]) -> list[int]:
    """The reads of one producer that the others already carry, by index: a
    read whose selector an earlier read repeats, and a read a wider read
    contains. Removing them drops no data: the first of the widest reads is
    never among them, so a whole read is kept and its narrower reads go."""
    return [
        index
        for index, read in enumerate(group)
        if _repeats_earlier(group, index)
        or any(_contains(other.selector, read.selector) for other in group)
    ]


def _repeats_earlier(group: Sequence[StepRead], index: int) -> bool:
    return any(other.selector == group[index].selector for other in group[:index])


def _contains(whole: tuple[str, ...], part: tuple[str, ...]) -> bool:
    """Whether a read of ``whole`` carries everything a read of ``part``
    does: the text carries every selector, the structured value every path
    in it, a path every longer path under it."""
    if whole == part:
        return False
    if whole == ():
        return True
    if whole[0] != STRUCTURED_SELECTOR_HEAD or part[:1] != (STRUCTURED_SELECTOR_HEAD,):
        return False
    return part[: len(whole)] == whole


def _duplicate_read_message(
    step: SuggestionStep,
    producer_order: int,
    group: Sequence[StepRead],
    *,
    contained: bool,
) -> str:
    joined = join_descriptions([describe_read(read, step) for read in group])
    if contained:
        return (
            f"Step {step.step_order} reads step {producer_order} {joined}, "
            "where the narrower read is part of what the whole read already "
            "carries."
        )
    return (
        f"Step {step.step_order} reads step {producer_order} twice, {joined}, "
        "so its model receives the same text twice on every run."
    )


__all__ = [
    "MAX_FLOW_SUGGESTIONS",
    "FlowSuggestion",
    "FlowSuggestionCode",
    "FlowSuggestionFix",
    "FlowSuggestionFixKind",
    "FlowSuggestionImpact",
    "FlowSuggestionImpactBasis",
    "FlowSuggestionLevel",
    "SuggestionFlow",
    "SuggestionStep",
    "analyze_flow",
    "suggestion_fingerprint",
]
