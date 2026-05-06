"""Pure diagnostic helper for AI Builder material-cost metrics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from intric.flows.ai_builder.ai_builder_domain_models import FlowDraftSpecCore
from intric.flows.enums import AIBuilderInputSource, AIBuilderInputType, FlowOutputType
from intric.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
)

_SOURCE_SURFACING_INPUT_TYPES = frozenset(
    {
        AIBuilderInputType.AUDIO.value,
        AIBuilderInputType.DOCUMENT.value,
        AIBuilderInputType.FILE.value,
    }
)


@dataclass(frozen=True, kw_only=True)
class MaterialMetricStep:
    """JSON-safe projection used by diagnostics without planner side effects."""

    step_ref: str
    step_order: int
    input_source: str
    input_type: str
    output_type: str
    question: str = ""


@dataclass(frozen=True, kw_only=True)
class MaterialMetrics:
    """Numeric material-cost facts; missing questions count as zero bytes."""

    binding_bytes: int
    fan_in_width: int
    structured_field_count: int
    whole_output_reference_count: int
    source_duplication_count: int
    all_previous_steps_count: int


def material_metric_steps_from_draft(
    spec: FlowDraftSpecCore,
) -> tuple[MaterialMetricStep, ...]:
    return tuple(
        MaterialMetricStep(
            step_ref=step.plan_step_ref,
            step_order=index,
            input_source=step.input_source.value,
            input_type=step.input_type.value,
            output_type=step.output_type.value,
            question=question_from_input_bindings(step.input_bindings),
        )
        for index, step in enumerate(spec.steps, start=1)
    )


def compute_material_metrics(
    steps: Sequence[MaterialMetricStep],
    *,
    form_field_names: Iterable[str] = (),
) -> MaterialMetrics:
    step_refs = {step.step_ref: step.step_order for step in steps}
    form_fields = set(form_field_names)
    source_step_refs = _source_surfacing_step_refs(steps)
    distinct_step_refs: set[str] = set()
    binding_bytes = 0
    structured_field_count = 0
    whole_output_reference_count = 0
    source_duplication_count = 0

    for step in steps:
        binding_bytes += len(step.question.encode("utf-8"))
        for reference in analyze_template(
            step.question,
            step_refs=step_refs,
            form_field_names=form_fields,
        ):
            if reference.kind is not TemplateReferenceKind.STEP:
                continue
            ref = reference.step_ref or reference.head
            distinct_step_refs.add(ref)
            if reference.tail.startswith("output.structured."):
                structured_field_count += 1
            if reference.tail in {"output.text", "output.structured"}:
                whole_output_reference_count += 1
            if ref in source_step_refs and reference.tail == "output.text":
                source_duplication_count += 1

    return MaterialMetrics(
        binding_bytes=binding_bytes,
        fan_in_width=len(distinct_step_refs),
        structured_field_count=structured_field_count,
        whole_output_reference_count=whole_output_reference_count,
        source_duplication_count=source_duplication_count,
        all_previous_steps_count=sum(
            1
            for step in steps
            if step.input_source == AIBuilderInputSource.ALL_PREVIOUS_STEPS.value
        ),
    )


def compute_step_material_metrics(
    steps: Sequence[MaterialMetricStep],
    *,
    step_order: int,
    form_field_names: Iterable[str] = (),
) -> MaterialMetrics:
    selected = [step for step in steps if step.step_order == step_order]
    if not selected:
        raise ValueError(f"Unknown step_order: {step_order}")
    step = selected[0]
    references = _step_references(
        step=step,
        steps=steps,
        form_field_names=form_field_names,
    )
    source_step_refs = _source_surfacing_step_refs(steps)
    return MaterialMetrics(
        binding_bytes=len(step.question.encode("utf-8")),
        fan_in_width=len(
            {reference.step_ref or reference.head for reference in references}
        ),
        structured_field_count=sum(
            1
            for reference in references
            if reference.tail.startswith("output.structured.")
        ),
        whole_output_reference_count=sum(
            1
            for reference in references
            if reference.tail in {"output.text", "output.structured"}
        ),
        source_duplication_count=sum(
            1
            for reference in references
            if (reference.step_ref or reference.head) in source_step_refs
            and reference.tail == "output.text"
        ),
        all_previous_steps_count=sum(
            1
            for item in steps
            if item.input_source == AIBuilderInputSource.ALL_PREVIOUS_STEPS.value
        ),
    )


def question_from_input_bindings(input_bindings: object) -> str:
    if not isinstance(input_bindings, dict):
        return ""
    bindings = cast(dict[str, object], input_bindings)
    question = bindings.get("question")
    return question if isinstance(question, str) else ""


def _source_surfacing_step_refs(
    steps: Sequence[MaterialMetricStep],
) -> frozenset[str]:
    return frozenset(
        step.step_ref
        for step in steps
        if step.input_source == AIBuilderInputSource.FLOW_INPUT.value
        and step.input_type in _SOURCE_SURFACING_INPUT_TYPES
        and step.output_type == FlowOutputType.TEXT.value
    )


def _step_references(
    *,
    step: MaterialMetricStep,
    steps: Sequence[MaterialMetricStep],
    form_field_names: Iterable[str],
) -> list[TemplateReference]:
    step_refs = {item.step_ref: item.step_order for item in steps}
    return [
        reference
        for reference in analyze_template(
            step.question,
            step_refs=step_refs,
            form_field_names=set(form_field_names),
        )
        if reference.kind is TemplateReferenceKind.STEP
    ]
