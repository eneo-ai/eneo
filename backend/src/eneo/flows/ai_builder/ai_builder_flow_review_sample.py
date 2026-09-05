"""Bounded run evidence a model may read when it judges a published flow.

The deterministic packet (`ai_builder_flow_review`) names what happened; the
sample adds the bounded content a model needs to say why: a structural
projection of the published definition, excerpts of recorded prompts, inputs
and outputs from a few admitted runs, and the packet's facts. Every excerpt
carries an availability marker so a model, and the reader of its suggestions,
can tell "not recorded" from "cut by budget": missing or truncated content
never supports a claim that a check or a useful output is absent.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.input_binding_contract_rules import (
    question_binding,
    source_ref_bindings,
)

if TYPE_CHECKING:
    # The packet lives in the review module, which imports this one; the
    # review module rebuilds `FlowReviewSample` once the packet class exists.
    from eneo.flows.ai_builder.ai_builder_flow_review import FlowReviewPacket

PER_EXCERPT_CHARS = 1500
TOTAL_EXCERPT_CHARS = 30_000
SAMPLE_COMPLETED_RUNS = 2
SAMPLE_FAILED_RUNS = 1
READ_DEADLINE_SECONDS = 20.0

ExcerptField = Literal["prompt", "input", "output"]
ExcerptAvailability = Literal[
    "included",
    "truncated",
    "omitted_by_budget",
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


class ReviewSampleBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    per_excerpt_chars: int
    total_excerpt_chars: int
    used_excerpt_chars: int


class FlowReviewSample(BaseModel):
    """What one model call may read; not persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet: "FlowReviewPacket"
    generated_at: datetime
    evidence_classification_level: int = Field(ge=0)
    steps: list[ReviewSampleStep]
    runs: list[ReviewSampleRun]
    excerpts: list[ReviewSampleExcerpt]
    budget: ReviewSampleBudget

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
            binding_summary=_binding_summary(step.input_bindings),
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


def _binding_summary(input_bindings: dict[str, Any] | None) -> str | None:
    if not input_bindings:
        return None
    refs = source_ref_bindings(input_bindings)
    if refs:
        return "source_refs: " + ", ".join(
            ref.step_ref + ("." + ".".join(ref.field_path) if ref.field_path else "")
            for ref in refs
        )
    if question_binding(input_bindings) is not None:
        return "question template"
    return None


class ExcerptBudget:
    """Allocates the total excerpt budget in read order."""

    def __init__(self) -> None:
        self.used = 0

    def take(self, text: str) -> tuple[str, ExcerptAvailability]:
        if self.used >= TOTAL_EXCERPT_CHARS:
            return "", "omitted_by_budget"
        allowed = min(PER_EXCERPT_CHARS, TOTAL_EXCERPT_CHARS - self.used)
        if len(text) <= allowed:
            self.used += len(text)
            return text, "included"
        self.used += allowed
        return text[:allowed], "truncated"


def excerpts_for_run(
    *,
    run_id: UUID,
    steps: list[RuntimeStep],
    step_result_records: tuple[dict[str, Any], ...],
    budget: ExcerptBudget,
) -> list[ReviewSampleExcerpt]:
    """Prompt, input and output excerpts per step, in step order.

    Availability is decided before budget: a mapped step records only its
    first item's prompt and a template fill records none, and a field a run
    never recorded is "not_recorded", never "omitted".
    """

    records_by_order = {
        int(record["step_order"]): record
        for record in step_result_records
        if isinstance(record.get("step_order"), int)
    }
    excerpts: list[ReviewSampleExcerpt] = []
    for step in steps:
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
                    budget=budget,
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
    budget: ExcerptBudget,
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
        return unavailable("not_recorded")
    text = _recorded_text(record, field)
    if text is None:
        return unavailable("not_recorded")
    taken, availability = budget.take(text)
    return ReviewSampleExcerpt(
        run_id=run_id,
        step_order=step.step_order,
        field=field,
        availability=availability,
        text=taken if availability != "omitted_by_budget" else None,
        recorded_chars=len(text),
    )


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
