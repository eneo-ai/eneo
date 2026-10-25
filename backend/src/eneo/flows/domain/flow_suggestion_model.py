"""The suggestion object and the analyzer's view of a draft.

A suggestion states what the draft proves about how it moves data: its code,
the steps it is about, typed ``params``, a message, its impact and how it is
fixed. ``DraftReads`` holds every read each step makes, computed once by
``step_lineage`` for all rules, so every rule judges the same reads publish
and the runtime resolve.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
    flow_output_mode_uses_completion_model,
)
from eneo.flows.flow_metadata import FlowFormSchemaParseMode, parse_flow_form_schema
from eneo.flows.flow_validators_template import EXACT_TEMPLATE_EXPRESSION_PATTERN
from eneo.flows.input_binding_contract_rules import InputBindingContractError
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    PROMPT_READ_SITE_PREFIX,
    FormFieldRead,
    StepRead,
    build_step_ref_mapping,
    step_form_field_reads,
    step_reads_by_channel,
)
from eneo.main.exceptions import BadRequestException

# At most this many suggestions per flow; the rest are cut after ordering.
MAX_FLOW_SUGGESTIONS = 50


class FlowSuggestionCode(str, Enum):
    """The closed set of suggestions. Clients render text from the code and
    ``params``; ``message`` is for API and chat consumers."""

    DUPLICATE_READ = "duplicate_read"
    BROAD_ALL_PREVIOUS_STEPS = "broad_all_previous_steps"
    WHOLE_STRUCTURED_READ = "whole_structured_read"
    UNREAD_CONTRACT_FIELDS = "unread_contract_fields"
    UNREAD_RESULT = "unread_result"
    RELAY_STEP = "relay_step"
    PER_ITEM_PROMPT_READ = "per_item_prompt_read"
    REPEATED_LONG_MATERIAL = "repeated_long_material"
    UNUSED_FORM_FIELD = "unused_form_field"
    # Measured from recent runs (``flow_suggestion_measured``).
    IDENTICAL_INPUTS = "identical_inputs"
    CONTEXT_HEADROOM = "context_headroom"
    FORMAT_FALLBACK = "format_fallback"


# What to do so a flow never earns the suggestion: one rule per code, for
# whoever designs a flow (the authoring chat's instructions are built from
# these). Each is one plain sentence.
FLOW_SUGGESTION_AUTHORING_RULES: Mapping[FlowSuggestionCode, str] = {
    FlowSuggestionCode.DUPLICATE_READ: (
        "Read an earlier result once: no {{ step_N.output.text }} in the "
        "prompt of a step that already gets step N as its input, and no "
        "second read of the same result in one step."
    ),
    FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS: (
        "Prefer source_refs or field paths to all_previous_steps when a step "
        "needs specific earlier results."
    ),
    FlowSuggestionCode.WHOLE_STRUCTURED_READ: (
        "Read the fields a step needs by field path rather than a whole JSON "
        "result with many fields."
    ),
    FlowSuggestionCode.UNREAD_CONTRACT_FIELDS: (
        "Declare only the output fields that later steps read."
    ),
    FlowSuggestionCode.UNREAD_RESULT: (
        "Add an intermediate step only when a later step reads its result."
    ),
    FlowSuggestionCode.RELAY_STEP: (
        "Add no step that only passes data along: let the later steps read "
        "its source directly."
    ),
    FlowSuggestionCode.PER_ITEM_PROMPT_READ: (
        "Put no whole earlier result in the prompt of a step that runs once "
        "per item: read a field, or extract what each item needs in a step "
        "before."
    ),
    FlowSuggestionCode.REPEATED_LONG_MATERIAL: (
        "Digest the same long material once, in one step the others read, "
        "rather than in several steps."
    ),
    FlowSuggestionCode.UNUSED_FORM_FIELD: (
        "Declare only the run form fields that a step reads."
    ),
    FlowSuggestionCode.IDENTICAL_INPUTS: (
        "Give a step each text once: read the original rather than also a "
        "step that copies it."
    ),
    FlowSuggestionCode.CONTEXT_HEADROOM: (
        "Keep what a step sends its model well below the model's limit: send "
        "each text once and only what the step needs."
    ),
    FlowSuggestionCode.FORMAT_FALLBACK: (
        "Ask for structured output only from a model that supports it, or "
        "let the step write text."
    ),
}


FlowSuggestionFixKind = Literal["patch", "assisted", "advice"]
FlowSuggestionLevel = Literal["high", "medium", "low"]
FlowSuggestionImpactBasis = Literal["definition", "runs"]

LEVEL_RANK: dict[FlowSuggestionLevel, int] = {"high": 0, "medium": 1, "low": 2}


class FlowSuggestionImpact(BaseModel):
    """What the suggestion costs. ``definition``: judged from the draft
    alone, at a level. ``runs``: measured over recent runs as well, with
    ``run_count`` runs of which the newest was of published ``version``;
    ``tokens_per_run`` is the measured cost of the duplicated or unused part
    (None when the runs measure the finding but not a token cost), and
    ``step_changed_since`` says the draft's step differs from the step in
    that version."""

    model_config = ConfigDict(frozen=True)

    basis: FlowSuggestionImpactBasis
    level: FlowSuggestionLevel
    tokens_per_run: int | None = None
    run_count: int | None = None
    version: int | None = None
    step_changed_since: bool | None = None

    @model_validator(mode="after")
    def _measured_exactly_from_runs(self) -> Self:
        measured = (self.run_count, self.version, self.step_changed_since)
        if self.basis == "runs":
            if any(value is None for value in measured):
                raise ValueError("A measured impact names its runs and version.")
        elif any(value is not None for value in (*measured, self.tokens_per_run)):
            raise ValueError("An impact from the definition carries no measurement.")
        return self


class FlowSuggestionFix(BaseModel):
    """How the suggestion is acted on: ``patch`` is a mechanical edit the core
    computes, ``assisted`` needs judgement (the authoring chat proposes it),
    ``advice`` is explained only.

    ``patch`` is present exactly for ``kind == "patch"``: the body of an
    editor update without ``expected_revision`` (``definition``,
    ``step_edits``, ``assistants``, ``step_order``, whichever the fix needs),
    as plain JSON."""

    model_config = ConfigDict(frozen=True)

    kind: FlowSuggestionFixKind
    patch: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _patch_exactly_for_a_patch(self) -> Self:
        if (self.kind == "patch") != (self.patch is not None):
            raise ValueError("A fix carries a patch exactly when its kind is patch.")
        return self


class FlowSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: FlowSuggestionCode
    # sha256 of the code, the affected steps and the premise that triggered
    # the suggestion; stable across unrelated edits, gone when the premise is.
    fingerprint: str
    # The affected steps; the first is the step the suggestion is about.
    # Empty for a suggestion about the run form.
    steps: tuple[UUID, ...]
    params: dict[str, Any] = Field(default_factory=dict)
    message: str
    impact: FlowSuggestionImpact
    fix: FlowSuggestionFix


@dataclass(frozen=True, slots=True)
class SuggestionStep:
    """A draft step as the analyzer reads it. ``prompt_text`` is the step
    assistant's prompt when the step's output mode uses a completion model,
    otherwise None (a prompt no model reads is no read);
    ``prompt_description`` is that prompt's description, kept by a fix that
    rewrites the prompt."""

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
    prompt_description: str | None = None
    has_review_policy: bool = False
    output_classification_override: int | None = None


@dataclass(frozen=True, slots=True)
class SuggestionFlow:
    """A draft as the analyzer reads it: its steps and its metadata (the run
    form among it), as saved."""

    steps: Sequence[SuggestionStep]
    metadata_json: Mapping[str, object] | None = None


def suggestion_fingerprint(
    code: FlowSuggestionCode,
    step_ids: Sequence[UUID],
    premise: Mapping[str, object],
) -> str:
    """The identity of a suggestion: its code, the steps it is about and the
    read shape that triggered it, hashed as canonical JSON.

    Steps are named by id and reads by ``read_premise``, never by step order
    or expression text: a step removed, inserted or moved before them, or a
    rename, rewrites the orders and the expressions but leaves the premise as
    it was. A premise that changes (a read removed, read from another step,
    another selector) changes the fingerprint."""

    return canonical_json_hash(
        {
            "code": code.value,
            "steps": [str(step_id) for step_id in step_ids],
            "premise": premise,
        }
    )


RUN_INPUT_PRODUCER = "run_input"
_SOURCE_REF_SITE_PREFIX = "input_bindings.source_refs["


def read_site_kind(site: str) -> str:
    """Where a read is written, without what renumbering or renaming steps
    rewrites: a prompt read without its expression, a source reference
    without its index (the producer and selector name the reference)."""
    if site.startswith(PROMPT_READ_SITE_PREFIX):
        return PROMPT_READ_SITE_PREFIX.removesuffix(":")
    if site.startswith(_SOURCE_REF_SITE_PREFIX):
        return _SOURCE_REF_SITE_PREFIX.removesuffix("[")
    return site


def read_premise(read: StepRead) -> dict[str, object]:
    """A read as a premise: its channel, the kind of site and its selector.
    The producer is named by the caller, by id."""
    return {
        "channel": read.channel,
        "site": read_site_kind(read.site),
        "selector": list(read.selector),
    }


def read_premises(reads: Sequence[StepRead]) -> list[dict[str, object]]:
    """``reads`` as premises, in an order that does not depend on where they
    are written."""
    return sorted((read_premise(read) for read in reads), key=canonical_json_hash)


def make_suggestion(
    code: FlowSuggestionCode,
    *,
    steps: Sequence[UUID],
    premise: Mapping[str, object],
    params: dict[str, Any],
    message: str,
    level: FlowSuggestionLevel,
    fix: FlowSuggestionFix,
    identity_steps: Sequence[UUID] | None = None,
    impact: FlowSuggestionImpact | None = None,
) -> FlowSuggestion:
    """``identity_steps``, when given, are the steps the fingerprint names
    in place of ``steps``: a suggestion that names a step for the reader
    without that step being part of its premise. ``impact``, when given,
    replaces the impact judged from the definition at ``level`` (a measured
    rule's)."""
    return FlowSuggestion(
        code=code,
        fingerprint=suggestion_fingerprint(
            code, steps if identity_steps is None else identity_steps, premise
        ),
        steps=tuple(steps),
        params=params,
        message=message,
        impact=impact or FlowSuggestionImpact(basis="definition", level=level),
        fix=fix,
    )


# A step's reads cannot be computed from a configuration the save would not
# accept; the rules then treat it as reading everything.
_UNREADABLE_ERRORS = (ValueError, InputBindingContractError, BadRequestException)


@dataclass(frozen=True, slots=True)
class DraftReads:
    """The draft's steps in step order and every read each makes, all
    channels, by ``step_lineage``. A step whose reads cannot be computed is
    ``unreadable``: rules that judge what is read skip it, and rules that
    judge what is not read treat it as reading every earlier step and form
    field."""

    steps: tuple[SuggestionStep, ...]
    metadata_json: Mapping[str, object] | None
    step_ref_mapping: dict[str, int]
    reads: Mapping[int, tuple[StepRead, ...]]
    form_field_reads: Mapping[int, tuple[FormFieldRead, ...]]
    form_fields: tuple[str, ...]
    unreadable: frozenset[int]

    @classmethod
    def of(cls, flow: SuggestionFlow) -> DraftReads:
        ordered = tuple(sorted(flow.steps, key=lambda step: step.step_order))
        step_ref_mapping = build_step_ref_mapping(
            {"step_order": step.step_order, "user_description": step.user_description}
            for step in ordered
        )
        form_fields = run_form_field_names(flow.metadata_json)
        reads: dict[int, tuple[StepRead, ...]] = {}
        field_reads: dict[int, tuple[FormFieldRead, ...]] = {}
        unreadable: set[int] = set()
        for step in ordered:
            try:
                reads[step.step_order] = step_reads(step, step_ref_mapping)
                field_reads[step.step_order] = step_form_field_reads(
                    input_source=step.input_source,
                    step_order=step.step_order,
                    input_bindings=step.input_bindings,
                    prompt_template=step.prompt_text,
                    output_mode=step.output_mode,
                    input_config=step.input_config,
                    output_config=step.output_config,
                    step_ref_mapping=step_ref_mapping,
                    form_field_names=form_fields,
                )
            except _UNREADABLE_ERRORS:
                reads[step.step_order] = ()
                field_reads[step.step_order] = ()
                unreadable.add(step.step_order)
        return cls(
            steps=ordered,
            metadata_json=flow.metadata_json,
            step_ref_mapping=step_ref_mapping,
            reads=reads,
            form_field_reads=field_reads,
            form_fields=form_fields,
            unreadable=frozenset(unreadable),
        )

    def step_at(self, order: int) -> SuggestionStep | None:
        return next((step for step in self.steps if step.step_order == order), None)

    def producer_key(self, order: int) -> str:
        """The producer at ``order`` as a premise names it: the step's id, or
        the run input (order 0)."""
        step = self.step_at(order)
        if step is None:
            return RUN_INPUT_PRODUCER if order == 0 else f"missing:{order}"
        return str(step.id)

    def model_reads(self, step: SuggestionStep) -> tuple[StepRead, ...]:
        """The reads that reach the step's model: its input and its prompt."""
        return tuple(
            read
            for read in self.reads[step.step_order]
            if read.channel in ("input", "prompt")
        )

    def readers_of(self, order: int) -> list[tuple[SuggestionStep, StepRead]]:
        """Every read of the step at ``order`` by a later step, any channel."""
        return [
            (step, read)
            for step in self.steps
            if step.step_order > order
            for read in self.reads[step.step_order]
            if read.step_order == order
        ]

    def unreadable_after(self, order: int) -> bool:
        return any(reader > order for reader in self.unreadable)

    @property
    def last_order(self) -> int:
        return self.steps[-1].step_order if self.steps else 0


def step_reads(
    step: SuggestionStep, step_ref_mapping: dict[str, int]
) -> tuple[StepRead, ...]:
    """Every read of ``step``, all channels. A fix checks the reads it leaves
    by reading a ``dataclasses.replace`` of the step."""
    return step_reads_by_channel(
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


def run_form_field_names(metadata_json: Mapping[str, object] | None) -> tuple[str, ...]:
    """The names of the run form's fields as saved, in their order."""
    try:
        schema = parse_flow_form_schema(
            metadata_json, mode=FlowFormSchemaParseMode.PERSISTED_READ
        )
    except BadRequestException:
        return ()
    if schema is None:
        return ()
    return tuple(name for item in schema.fields if (name := item.name.strip()))


def uses_completion_model(step: SuggestionStep) -> bool:
    return flow_output_mode_uses_completion_model(step.output_mode)


def exact_expression(text: str) -> str | None:
    """The expression of a text that is exactly one template expression."""
    match = EXACT_TEMPLATE_EXPRESSION_PATTERN.match(text)
    return match.group(1).strip() if match is not None else None


def read_payload(read: StepRead) -> dict[str, object]:
    return {"channel": read.channel, "site": read.site, "selector": list(read.selector)}


def describe_read(read: StepRead, step: SuggestionStep) -> str:
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


def join_descriptions(described: Sequence[str]) -> str:
    if len(described) <= 2:
        return " and ".join(described)
    return ", ".join(described[:-1]) + " and " + described[-1]


__all__ = [
    "LEVEL_RANK",
    "MAX_FLOW_SUGGESTIONS",
    "DraftReads",
    "FlowSuggestion",
    "FlowSuggestionCode",
    "FlowSuggestionFix",
    "FlowSuggestionFixKind",
    "FlowSuggestionImpact",
    "FlowSuggestionImpactBasis",
    "FlowSuggestionLevel",
    "SuggestionFlow",
    "SuggestionStep",
    "describe_read",
    "exact_expression",
    "join_descriptions",
    "make_suggestion",
    "read_payload",
    "run_form_field_names",
    "step_reads",
    "suggestion_fingerprint",
    "uses_completion_model",
]
