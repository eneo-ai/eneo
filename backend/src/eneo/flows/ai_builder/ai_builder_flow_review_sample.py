"""Bounded run evidence a model may read when it judges a published flow.

The deterministic packet (`ai_builder_flow_review`) names what happened; the
sample adds the bounded content a model needs to say why: a structural
projection of the published definition, excerpts of recorded prompts, inputs
and outputs from a few admitted runs, and the packet's facts. Every excerpt
carries an availability marker so a model, and the reader of its suggestions,
can tell "not recorded" from "cut by budget": missing or truncated content
never supports a claim that a check or a useful output is absent.

Excerpts are read whole. How much of them a model gets is decided later, by
the request that carries them, against that model's window: see
`fit_sample_excerpts`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_text_fitting import fit_text_allocations
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.input_binding_contract_rules import describe_input_bindings

if TYPE_CHECKING:
    # The packet lives in the review module, which imports this one; the
    # review module rebuilds `FlowReviewSample` once the packet class exists.
    from eneo.flows.ai_builder.ai_builder_flow_review import (
        FlowReviewPacket,
        FlowReviewRunAdmission,
    )

SAMPLE_COMPLETED_RUNS = 2
SAMPLE_FAILED_RUNS = 1
READ_DEADLINE_SECONDS = 20.0

T = TypeVar("T")

ExcerptField = Literal["prompt", "input", "output"]
ExcerptAvailability = Literal[
    "included",
    "truncated",
    # The runtime stored only a prefix of a step text and moved the whole to a
    # file the review never reads: the prefix is a preview, not the output.
    "truncated_by_runtime",
    "omitted_by_budget",
    "omitted_by_reader",
    "not_recorded",
    "unavailable_mapped_prompt",
    # A mapped step stores a summary of its calls where the input text goes.
    "unavailable_mapped_input",
    "unavailable_template_fill",
]


class ReviewSampleStep(BaseModel):
    """The published definition's shape for one step, without instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_order: int
    label: str | None
    input_source: str
    input_type: str
    output_type: str
    output_mode: str
    binding_summary: str | None
    output_contract_fields: list[str]
    review_mode: str | None


class ReviewSampleRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    status: str
    evidence_classification_level: int = Field(ge=0)


class ReviewSampleExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    step_order: int
    field: ExcerptField
    availability: ExcerptAvailability
    text: str | None = None
    recorded_chars: int | None = None


class FlowReviewSample(BaseModel):
    """What one model call may read; not persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet: "FlowReviewPacket"
    generated_at: datetime
    evidence_classification_level: int = Field(ge=0)
    steps: list[ReviewSampleStep]
    runs: list[ReviewSampleRun]
    excerpts: list[ReviewSampleExcerpt]

    @property
    def run_ids(self) -> list[UUID]:
        return [run.run_id for run in self.runs]


def select_sample_run_ids(packet: "FlowReviewPacket") -> list[UUID]:
    """The newest completed runs plus the newest failed run when one exists.

    The cohort lists are newest first. One of the slots goes to a failed run so
    a failure analysis has something to read; without one, all slots are
    completed runs.
    """

    completed = list(packet.cohort.completed_run_ids)
    failed = list(packet.cohort.failed_run_ids)
    if failed:
        return completed[:SAMPLE_COMPLETED_RUNS] + failed[:SAMPLE_FAILED_RUNS]
    return completed[: SAMPLE_COMPLETED_RUNS + SAMPLE_FAILED_RUNS]


_ADMISSION_NOTES_SV: dict[str, str] = {
    "withheld_usage_not_measured": (
        "tokenandel utelämnad, minst ett steg saknar kvitto från leverantören"
    ),
    "withheld_timing_missing": (
        "tidsandel utelämnad, minst ett steg saknar tidsstämplar"
    ),
    "withheld_lineage_untracked": (
        "indataspårning saknas, användning av utdata inte bedömd"
    ),
}


def admission_note_sv(item: FlowReviewRunAdmission | None) -> str | None:
    """What a run could not prove, for a model reading it; None when nothing
    was withheld or the run has no admission (it is outside the cohort)."""
    if item is None:
        return None
    notes = [
        _ADMISSION_NOTES_SV[value]
        for value in (item.token_share, item.latency_share, item.consumption)
        if value in _ADMISSION_NOTES_SV
    ]
    return "; ".join(notes) or None


def structural_steps(steps: list[RuntimeStep]) -> list[ReviewSampleStep]:
    return [
        ReviewSampleStep(
            step_order=step.step_order,
            label=step.user_description,
            input_source=step.input_source,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
            binding_summary=describe_input_bindings(step.input_bindings),
            output_contract_fields=(
                schema_leaf_property_names(step.output_contract)
                if step.output_contract is not None
                else []
            ),
            review_mode=(
                step.review_policy.mode.value
                if step.review_policy is not None
                else None
            ),
        )
        for step in steps
    ]


def reader_omitted_step_results(debug_export: dict[str, Any]) -> bool:
    """Whether the evidence reader left step results unread under its own limits.

    The reader records row and byte omissions per section; a step result it
    did not return is unread, not unrecorded, and the sample must say so.
    """

    run_export = debug_export.get("run")
    if not isinstance(run_export, dict):
        return False
    summary = cast(dict[str, Any], run_export).get("summary")
    if not isinstance(summary, dict):
        return False
    omissions = cast(dict[str, Any], summary).get("omissions")
    if not isinstance(omissions, list):
        return False
    return any(
        isinstance(item, dict)
        and cast(dict[str, Any], item).get("section") == "step_results"
        for item in cast(list[object], omissions)
    )


def excerpts_for_run(
    *,
    run_id: UUID,
    steps: list[RuntimeStep],
    step_result_records: tuple[dict[str, Any], ...],
    reader_omitted_records: bool = False,
    step_orders: Collection[int] | None = None,
) -> list[ReviewSampleExcerpt]:
    """Prompt, input and output excerpts per step, in step order, read whole.

    Availability is decided here: a mapped step records only its first
    item's prompt and a template fill records none; a field a run never
    recorded is "not_recorded"; a result the reader left unread under its
    own limits is "omitted_by_reader"; a text the runtime persisted as a
    prefix plus a file is "truncated_by_runtime". "truncated" and
    "omitted_by_budget" are set later by `fit_sample_excerpts`, against a
    real request.
    ``step_orders`` keeps only the named steps' excerpts: the bundle is still
    read and audited whole, the prompt allocation is what stays bounded.
    """

    records_by_order = {
        int(record["step_order"]): record
        for record in step_result_records
        if isinstance(record.get("step_order"), int)
    }
    excerpts: list[ReviewSampleExcerpt] = []
    for step in steps:
        if step_orders is not None and step.step_order not in step_orders:
            continue
        record = records_by_order.get(step.step_order)
        mapped = record is not None and _is_mapped_record(record)
        for field in ("prompt", "input", "output"):
            excerpts.append(
                _excerpt(
                    run_id=run_id,
                    step=step,
                    field=field,
                    record=record,
                    mapped=mapped,
                    missing_record_availability=(
                        "omitted_by_reader"
                        if reader_omitted_records
                        else "not_recorded"
                    ),
                )
            )
    return excerpts


def _excerpt(
    *,
    run_id: UUID,
    step: RuntimeStep,
    field: ExcerptField,
    record: dict[str, Any] | None,
    mapped: bool,
    missing_record_availability: ExcerptAvailability,
) -> ReviewSampleExcerpt:
    def unavailable(availability: ExcerptAvailability) -> ReviewSampleExcerpt:
        return ReviewSampleExcerpt(
            run_id=run_id,
            step_order=step.step_order,
            field=field,
            availability=availability,
        )

    if field == "prompt":
        if step.output_mode == "template_fill":
            return unavailable("unavailable_template_fill")
        if mapped:
            return unavailable("unavailable_mapped_prompt")
    if field == "input" and mapped:
        return unavailable("unavailable_mapped_input")
    if record is None:
        return unavailable(missing_record_availability)
    recorded = _recorded_text(record, field)
    if recorded is None:
        return unavailable("not_recorded")
    text, availability = recorded
    return ReviewSampleExcerpt(
        run_id=run_id,
        step_order=step.step_order,
        field=field,
        availability=availability,
        text=text,
        recorded_chars=len(text),
    )


# ---- fitting and quoting -------------------------------------------------------


ReviewPromptGroups = tuple[tuple[int, ...], ...]


def review_prompt_groups(excerpts: Sequence[ReviewSampleExcerpt]) -> ReviewPromptGroups:
    """Freeze equality of complete instructions before fitting can hide differences."""
    by_instruction: dict[tuple[int, str, int | None], list[int]] = {}
    for index, excerpt in enumerate(excerpts):
        if (
            excerpt.field == "prompt"
            and excerpt.availability == "included"
            and excerpt.text
        ):
            key = (excerpt.step_order, excerpt.text, excerpt.recorded_chars)
            by_instruction.setdefault(key, []).append(index)
    return tuple(
        tuple(indices)
        for indices in by_instruction.values()
        if len(indices) > 1
        and len({excerpts[index].run_id for index in indices}) == len(indices)
    )


def readable_prompt_groups(
    excerpts: Sequence[ReviewSampleExcerpt],
    prompt_groups: ReviewPromptGroups | None,
) -> ReviewPromptGroups:
    """Only share matching readable members of the original instruction groups.

    Pass frozen groups to preserve sharing after truncation; None recomputes
    groups from complete excerpts only.
    """
    groups = review_prompt_groups(excerpts) if prompt_groups is None else prompt_groups
    readable: list[tuple[int, ...]] = []
    for indices in groups:
        if len(indices) < 2 or any(
            index < 0 or index >= len(excerpts) for index in indices
        ):
            continue
        first = excerpts[indices[0]]
        if not first.text or first.availability not in ("included", "truncated"):
            continue
        if len({excerpts[index].run_id for index in indices}) != len(indices):
            continue
        if all(
            excerpts[index].field == "prompt"
            and excerpts[index].step_order == first.step_order
            and excerpts[index].text == first.text
            and excerpts[index].availability == first.availability
            and excerpts[index].recorded_chars == first.recorded_chars
            for index in indices
        ):
            readable.append(indices)
    return tuple(readable)


def fit_excerpts(
    excerpts: Sequence[ReviewSampleExcerpt],
    *,
    render: Callable[[list[ReviewSampleExcerpt]], T],
    fits: Callable[[T], bool],
    prompt_groups: ReviewPromptGroups | None = None,
    suffix_indices: Collection[int] = (),
) -> T:
    """The carrier with as much excerpt text as ``fits`` allows.

    ``render`` rebuilds the carrier (a sample, an evidence packet) around a
    candidate excerpt list; ``fits`` measures it the way the request will be
    measured. Readable excerpts share the room fairly; an included one cut
    short is "truncated" and one left without room is "omitted_by_budget",
    so the model and the reader of its answer are told what was not read. A
    runtime preview shares the room too (it can be as long as any inline
    text) and stays "truncated_by_runtime" however short it gets: cutting a
    prefix leaves a prefix.
    """

    allocation_owner = {
        index: indices[0]
        for indices in readable_prompt_groups(excerpts, prompt_groups)
        for index in indices
    }
    readable = [
        (index, excerpt.text)
        for index, excerpt in enumerate(excerpts)
        if excerpt.availability in _FITTED
        and excerpt.text
        and allocation_owner.get(index, index) == index
    ]

    def render_allocations(allocations: Mapping[int, int]) -> T:
        fitted: list[ReviewSampleExcerpt] = []
        for index, excerpt in enumerate(excerpts):
            if excerpt.availability not in _FITTED or not excerpt.text:
                fitted.append(excerpt)
                continue
            owner = allocation_owner.get(index, index)
            allowed = min(allocations.get(owner, 0), len(excerpt.text))
            if allowed == len(excerpt.text):
                fitted.append(excerpt)
            elif allowed > 0:
                fitted.append(
                    excerpt.model_copy(
                        update={
                            "availability": (
                                "truncated"
                                if excerpt.availability == "included"
                                else excerpt.availability
                            ),
                            "text": excerpt.text[-allowed:]
                            if index in suffix_indices
                            else excerpt.text[:allowed],
                        }
                    )
                )
            else:
                fitted.append(
                    excerpt.model_copy(
                        update={"availability": "omitted_by_budget", "text": None}
                    )
                )
        return render(fitted)

    return fit_text_allocations(readable, render=render_allocations, fits=fits)


_FITTED: frozenset[str] = frozenset({"included", "truncated_by_runtime"})


def fit_sample_excerpts(
    sample: FlowReviewSample,
    *,
    fits: Callable[[FlowReviewSample], bool],
    prompt_groups: ReviewPromptGroups | None = None,
) -> FlowReviewSample:
    """The sample with as much excerpt text as the request can carry."""

    return fit_excerpts(
        sample.excerpts,
        render=lambda excerpts: sample.model_copy(update={"excerpts": excerpts}),
        fits=fits,
        prompt_groups=prompt_groups,
    )


PROMPT_LINE_BREAKERS = ("\u2028", "\u2029", "\u0085")


def quoted_excerpt(text: str | None) -> str:
    """Recorded text as one quoted line that cannot become several.

    An excerpt is evidence to weigh, and it reaches a model's prompt. Written
    as a quoted, escaped string on a single line, it cannot open a heading,
    close the block it sits in, or pose as the instructions around it.
    """

    quoted = json.dumps(text or "", ensure_ascii=False)
    for breaker in PROMPT_LINE_BREAKERS:
        quoted = quoted.replace(breaker, f"\\u{ord(breaker):04x}")
    return quoted


def _is_mapped_record(record: Mapping[str, Any]) -> bool:
    """Whether the step ran as several provider calls (per item or per source).

    A mapped step records only its first call's instruction and a summary in
    place of the input text; neither is the evidence of any one call.
    """
    output = record.get("output_payload_json")
    if isinstance(output, dict):
        output_mapping = cast(dict[str, object], output)
        if output_mapping.get("item_map_execution_mode") == "per_item":
            return True
    parameters = record.get("model_parameters_json")
    if isinstance(parameters, dict):
        parameters_mapping = cast(dict[str, object], parameters)
        if parameters_mapping.get("runtime_input_execution_mode") == "per_source":
            return True
    return False


def _recorded_text(
    record: dict[str, Any], field: ExcerptField
) -> tuple[str, ExcerptAvailability] | None:
    """The recorded text and whether it is the whole of what the step recorded."""

    if field == "prompt":
        prompt = record.get("effective_prompt")
        return (prompt, "included") if isinstance(prompt, str) and prompt else None
    payload: object = record.get(
        "input_payload_json" if field == "input" else "output_payload_json"
    )
    if payload is None:
        return None
    if isinstance(payload, dict):
        mapping = cast(dict[str, object], payload)
        text = mapping.get("text")
        if isinstance(text, str):
            return (text, _text_availability(mapping)) if text else None
        return json.dumps(mapping, ensure_ascii=False, sort_keys=True), "included"
    if isinstance(payload, str):
        return (payload, "included") if payload else None
    return json.dumps(payload, ensure_ascii=False), "included"


def _text_availability(payload: Mapping[str, object]) -> ExcerptAvailability:
    """Whether the payload's text is the step's whole text or a runtime preview.

    The runtime marks a text it stored as a prefix plus a file; the domain
    interpreter owns that shape. Evidence reads are redacted, which can
    rewrite the preview and fail the interpreter's byte check: the mark alone
    still says the text is a prefix, and a prefix is never called included.
    """

    if OUTPUT_TEXT_OVERFLOW_KEY not in payload:
        return "included"
    try:
        step_text = interpret_step_text(payload)
    except StepOutputMetadataError:
        return "truncated_by_runtime"
    return (
        "truncated_by_runtime"
        if isinstance(step_text, FileBackedStepText)
        else "included"
    )
