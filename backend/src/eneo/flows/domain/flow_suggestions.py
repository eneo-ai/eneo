"""Suggestions about a draft flow: where it moves the same data twice.

Pure functions over the draft. A suggestion states what the definition
proves, never blocks publishing and changes nothing by itself. The reads it
judges are the ones ``step_lineage`` resolves for publish and the runtime,
so there is one interpretation of what a step reads.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
    flow_output_mode_uses_completion_model,
)
from eneo.flows.flow_validators_template import EXACT_TEMPLATE_EXPRESSION_PATTERN
from eneo.flows.input_binding_contract_rules import question_binding
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    PROMPT_READ_SITE_PREFIX,
    STRUCTURED_SELECTOR_HEAD,
    StepRead,
    build_step_ref_mapping,
    step_reads_by_channel,
)

# At most this many suggestions per flow; the rest are cut after ordering.
MAX_FLOW_SUGGESTIONS = 50


class FlowSuggestionCode(str, Enum):
    """The closed set of suggestions. Clients render text from the code and
    ``params``; ``message`` is for API and chat consumers."""

    DUPLICATE_READ = "duplicate_read"


FlowSuggestionFixKind = Literal["patch", "assisted", "advice"]
FlowSuggestionLevel = Literal["high", "medium", "low"]
FlowSuggestionImpactBasis = Literal["definition"]

_LEVEL_RANK: dict[FlowSuggestionLevel, int] = {"high": 0, "medium": 1, "low": 2}


class FlowSuggestionImpact(BaseModel):
    """What the suggestion costs: judged from the definition alone, at a
    level; measured bases and their numbers come with run evidence."""

    model_config = ConfigDict(frozen=True)

    basis: FlowSuggestionImpactBasis
    level: FlowSuggestionLevel


class FlowSuggestionFix(BaseModel):
    """How the suggestion is acted on: ``patch`` is a mechanical edit the core
    computes, ``assisted`` needs judgement (the authoring chat proposes it),
    ``advice`` is explained only."""

    model_config = ConfigDict(frozen=True)

    kind: FlowSuggestionFixKind


class FlowSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: FlowSuggestionCode
    # sha256 of the code, the affected steps and the premise that triggered
    # the suggestion; stable across unrelated edits, gone when the premise is.
    fingerprint: str
    # The affected steps; the first is the step the suggestion is about.
    steps: tuple[UUID, ...]
    params: dict[str, Any] = Field(default_factory=dict)
    message: str
    impact: FlowSuggestionImpact
    fix: FlowSuggestionFix


@dataclass(frozen=True, slots=True)
class SuggestionStep:
    """A draft step as the analyzer reads it. ``prompt_text`` is the step
    assistant's prompt when the step's output mode uses a completion model,
    otherwise None (a prompt no model reads is no read)."""

    id: UUID
    step_order: int
    user_description: str | None
    input_source: FlowInputSource | str
    input_type: FlowInputType | str
    input_bindings: Mapping[str, object] | None
    input_config: Mapping[str, object] | None
    output_mode: FlowOutputMode | str
    output_type: FlowOutputType | str
    output_contract: Mapping[str, object] | None
    output_config: Mapping[str, object] | None
    prompt_text: str | None
    assistant_id: UUID


def suggestion_fingerprint(
    code: FlowSuggestionCode,
    step_ids: Sequence[UUID],
    premise: Mapping[str, object],
) -> str:
    """The identity of a suggestion: its code, the steps it is about and the
    read shape that triggered it, hashed as canonical JSON."""

    return canonical_json_hash(
        {
            "code": code.value,
            "steps": [str(step_id) for step_id in step_ids],
            "premise": premise,
        }
    )


def analyze_flow(steps: Sequence[SuggestionStep]) -> tuple[FlowSuggestion, ...]:
    """Every suggestion the draft proves, ordered by impact level (high,
    medium, low), then step order, then fingerprint, at most
    ``MAX_FLOW_SUGGESTIONS``."""

    ordered = sorted(steps, key=lambda step: step.step_order)
    step_ref_mapping = build_step_ref_mapping(
        {"step_order": step.step_order, "user_description": step.user_description}
        for step in ordered
    )
    ids_by_order = {step.step_order: step.id for step in ordered}
    suggestions: list[tuple[tuple[int, int, str], FlowSuggestion]] = []
    for step in ordered:
        for suggestion in _duplicate_reads(step, step_ref_mapping, ids_by_order):
            key = (
                _LEVEL_RANK[suggestion.impact.level],
                step.step_order,
                suggestion.fingerprint,
            )
            suggestions.append((key, suggestion))
    suggestions.sort(key=lambda item: item[0])
    return tuple(suggestion for _, suggestion in suggestions[:MAX_FLOW_SUGGESTIONS])


def _duplicate_reads(
    step: SuggestionStep,
    step_ref_mapping: dict[str, int],
    ids_by_order: Mapping[int, UUID],
) -> list[FlowSuggestion]:
    """``duplicate_read``: the same earlier step reaches the step's model
    twice, through its input and its prompt or twice in one of them.

    Two reads of the same selector (the whole text twice, one field twice)
    are a duplicate. A whole read next to a narrower read of the same result
    (the text and a field of it, the structured value and a path in it) is
    reported as contained: the narrower read adds nothing the whole does not
    carry. ``params["redundant_reads"]`` names, by index into ``reads``, the
    reads a fix removes: a repeated read, and every read a wider one
    contains, never the whole read. Steps without a completion model read
    nothing into a model.
    """
    if not flow_output_mode_uses_completion_model(step.output_mode):
        return []
    reads = [
        read
        for read in step_reads_by_channel(
            input_source=step.input_source,
            step_order=step.step_order,
            input_bindings=step.input_bindings,
            prompt_template=step.prompt_text,
            output_mode=step.output_mode,
            input_config=step.input_config,
            output_config=step.output_config,
            step_ref_mapping=step_ref_mapping,
            max_prior_step_order=step.step_order - 1,
        )
        if read.channel in ("input", "prompt")
    ]
    by_producer: dict[int, list[StepRead]] = defaultdict(list)
    for read in reads:
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
        fix_kind: FlowSuggestionFixKind = (
            "patch"
            if all(_is_standalone_read(step, group[index]) for index in redundant)
            else "assisted"
        )
        producer_id = ids_by_order.get(producer_order)
        step_ids = (step.id, *((producer_id,) if producer_id is not None else ()))
        premise = {
            "producer_step_order": producer_order,
            "sites": [{"channel": read.channel, "site": read.site} for read in group],
        }
        suggestions.append(
            FlowSuggestion(
                code=FlowSuggestionCode.DUPLICATE_READ,
                fingerprint=suggestion_fingerprint(
                    FlowSuggestionCode.DUPLICATE_READ, step_ids, premise
                ),
                steps=step_ids,
                params={
                    "producer_step_order": producer_order,
                    "producer_step_id": (
                        str(producer_id) if producer_id is not None else None
                    ),
                    "contained": contained,
                    "redundant_reads": redundant,
                    "reads": [
                        {
                            "channel": read.channel,
                            "site": read.site,
                            "selector": list(read.selector),
                        }
                        for read in group
                    ],
                },
                message=_duplicate_read_message(
                    step, producer_order, group, contained=contained
                ),
                impact=FlowSuggestionImpact(basis="definition", level=level),
                fix=FlowSuggestionFix(kind=fix_kind),
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


def _is_standalone_read(step: SuggestionStep, read: StepRead) -> bool:
    """Whether removing the read is mechanical: its expression is alone on
    its line in the prompt, the question binding is exactly its expression,
    or it is a source ref (one entry of a list)."""
    if read.site.startswith(PROMPT_READ_SITE_PREFIX):
        expression = read.site.removeprefix(PROMPT_READ_SITE_PREFIX)
        return any(
            _exact_expression(line) == expression
            for line in (step.prompt_text or "").splitlines()
        )
    if read.site == "input_bindings.question":
        question = question_binding(step.input_bindings)
        return question is not None and _exact_expression(question) is not None
    return read.site.startswith("input_bindings.source_refs[")


def _exact_expression(text: str) -> str | None:
    match = EXACT_TEMPLATE_EXPRESSION_PATTERN.match(text)
    return match.group(1).strip() if match is not None else None


def _describe_read(read: StepRead, step: SuggestionStep) -> str:
    if read.site == INPUT_SOURCE_READ_SITE:
        return f"as its input ({FlowInputSource(step.input_source).value})"
    if read.site == "input_bindings.question":
        return "in its question"
    if read.site.startswith("input_bindings.source_refs["):
        index = read.site.removeprefix("input_bindings.source_refs[").rstrip("]")
        return f"in source reference {int(index) + 1}"
    if read.site.startswith(PROMPT_READ_SITE_PREFIX):
        expression = read.site.removeprefix(PROMPT_READ_SITE_PREFIX)
        return f"in its prompt ({{{{ {expression} }}}})"
    return f"in {read.site}"


def _duplicate_read_message(
    step: SuggestionStep,
    producer_order: int,
    group: Sequence[StepRead],
    *,
    contained: bool,
) -> str:
    described = [_describe_read(read, step) for read in group]
    joined = (
        " and ".join(described)
        if len(described) == 2
        else ", ".join(described[:-1]) + " and " + described[-1]
    )
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
    "SuggestionStep",
    "analyze_flow",
    "suggestion_fingerprint",
]
