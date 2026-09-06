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
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_text_fitting import fit_text_allocations
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.input_binding_contract_rules import describe_input_bindings

if TYPE_CHECKING:
    # The packet lives in the review module, which imports this one; the
    # review module rebuilds `FlowReviewSample` once the packet class exists.
    from eneo.flows.ai_builder.ai_builder_flow_review import FlowReviewPacket

SAMPLE_COMPLETED_RUNS = 2
SAMPLE_FAILED_RUNS = 1
READ_DEADLINE_SECONDS = 20.0

ExcerptField = Literal["prompt", "input", "output"]
ExcerptAvailability = Literal[
    "included",
    "truncated",
    "omitted_by_budget",
    "omitted_by_reader",
    "not_recorded",
    "unavailable_mapped_prompt",
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
    own limits is "omitted_by_reader". "truncated" and "omitted_by_budget"
    are set later by `fit_sample_excerpts`, against a real request.
    ``step_orders`` keeps only the named steps, so a turn about two steps
    never spends its budget on the others.
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
        mapped = record is not None and _is_mapped_output(
            record.get("output_payload_json")
        )
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
    if record is None:
        return unavailable(missing_record_availability)
    text = _recorded_text(record, field)
    if text is None:
        return unavailable("not_recorded")
    return ReviewSampleExcerpt(
        run_id=run_id,
        step_order=step.step_order,
        field=field,
        availability="included",
        text=text,
        recorded_chars=len(text),
    )


# ---- fitting and quoting -------------------------------------------------------


def fit_sample_excerpts(
    sample: FlowReviewSample,
    *,
    fits: Callable[[FlowReviewSample], bool],
) -> FlowReviewSample:
    """The sample with as much excerpt text as the request can carry.

    ``fits`` measures a candidate the way the provider call will be measured.
    Included excerpts share the room fairly; one cut short is "truncated" and
    one left without room is "omitted_by_budget", so the model and the reader
    of its answer are told what was not read.
    """

    readable = [
        (index, excerpt.text)
        for index, excerpt in enumerate(sample.excerpts)
        if excerpt.availability == "included" and excerpt.text
    ]

    def render(allocations: Mapping[int, int]) -> FlowReviewSample:
        excerpts: list[ReviewSampleExcerpt] = []
        for index, excerpt in enumerate(sample.excerpts):
            if excerpt.availability != "included" or not excerpt.text:
                excerpts.append(excerpt)
                continue
            allowed = min(allocations.get(index, 0), len(excerpt.text))
            if allowed == len(excerpt.text):
                excerpts.append(excerpt)
            elif allowed > 0:
                excerpts.append(
                    excerpt.model_copy(
                        update={
                            "availability": "truncated",
                            "text": excerpt.text[:allowed],
                        }
                    )
                )
            else:
                excerpts.append(
                    excerpt.model_copy(
                        update={"availability": "omitted_by_budget", "text": None}
                    )
                )
        return sample.model_copy(update={"excerpts": excerpts})

    return fit_text_allocations(readable, render=render, fits=fits)


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


def _is_mapped_output(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    mapping = cast(dict[str, object], payload)
    return mapping.get("item_map_execution_mode") == "per_item"


def _recorded_text(record: dict[str, Any], field: ExcerptField) -> str | None:
    if field == "prompt":
        prompt = record.get("effective_prompt")
        return prompt if isinstance(prompt, str) and prompt else None
    payload: object = record.get(
        "input_payload_json" if field == "input" else "output_payload_json"
    )
    if payload is None:
        return None
    if isinstance(payload, dict):
        mapping = cast(dict[str, object], payload)
        text = mapping.get("text")
        if isinstance(text, str):
            return text or None
        return json.dumps(mapping, ensure_ascii=False, sort_keys=True)
    if isinstance(payload, str):
        return payload or None
    return json.dumps(payload, ensure_ascii=False)
