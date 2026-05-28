"""Pure diagnostic helper for AI Builder material-cost metrics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_source_material import question_binding
from intric.flows.ai_builder.ai_builder_underlag_policy import is_source_surfacing_text
from intric.flows.enums import AIBuilderInputSource, FlowOutputType
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputType,
)
from intric.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
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
    """Material-cost facts; missing questions count as zero bytes."""

    binding_bytes: int
    fan_in_width: int
    structured_field_count: int
    whole_output_reference_count: int
    source_duplication_count: int
    all_previous_steps_count: int
    structured_prior_count: int
    structured_prior_ref_count: int
    structured_prior_coverage_ratio: float
    missing_structured_prior_steps: tuple[str, ...]
    text_prior_count: int
    text_prior_ref_count: int
    text_prior_coverage_ratio: float
    missing_text_prior_steps: tuple[str, ...]
    runtime_input_reference_count: int
    form_field_reference_count: int


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
            question=question_binding(step.input_bindings) or "",
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
    runtime_input_reference_count = 0
    form_field_reference_count = 0
    structured_prior_count = 0
    structured_prior_ref_count = 0
    missing_structured_prior_refs: list[str] = []
    text_prior_count = 0
    text_prior_ref_count = 0
    missing_text_prior_refs: list[str] = []

    for step in steps:
        binding_bytes += len(step.question.encode("utf-8"))
        references = analyze_template(
            step.question,
            step_refs=step_refs,
            form_field_names=form_fields,
        )
        coverage = _structured_prior_coverage(
            step=step,
            steps=steps,
            references=references,
        )
        text_coverage = _text_prior_coverage(
            step=step,
            steps=steps,
            references=references,
        )
        structured_prior_count += coverage.prior_count
        structured_prior_ref_count += len(coverage.referenced_prior_refs)
        missing_structured_prior_refs.extend(coverage.missing_prior_refs)
        text_prior_count += text_coverage.prior_count
        text_prior_ref_count += len(text_coverage.referenced_prior_refs)
        missing_text_prior_refs.extend(text_coverage.missing_prior_refs)
        for reference in references:
            if (
                reference.kind is TemplateReferenceKind.RUNTIME
                and reference.head == "step_input"
                and reference.path_error_code is None
            ):
                runtime_input_reference_count += 1
            if (
                reference.kind is TemplateReferenceKind.FORM_FIELD
                or reference.form_field_name is not None
            ) and reference.path_error_code is None:
                form_field_reference_count += 1
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
        structured_prior_count=structured_prior_count,
        structured_prior_ref_count=structured_prior_ref_count,
        structured_prior_coverage_ratio=_coverage_ratio(
            referenced_count=structured_prior_ref_count,
            prior_count=structured_prior_count,
        ),
        missing_structured_prior_steps=_unique_refs(missing_structured_prior_refs),
        text_prior_count=text_prior_count,
        text_prior_ref_count=text_prior_ref_count,
        text_prior_coverage_ratio=_coverage_ratio(
            referenced_count=text_prior_ref_count,
            prior_count=text_prior_count,
        ),
        missing_text_prior_steps=_unique_refs(missing_text_prior_refs),
        runtime_input_reference_count=runtime_input_reference_count,
        form_field_reference_count=form_field_reference_count,
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
    return _compute_step_material_metrics(
        step=selected[0],
        steps=steps,
        form_field_names=form_field_names,
        source_step_refs=_source_surfacing_step_refs(steps),
    )


def _compute_step_material_metrics(
    *,
    step: MaterialMetricStep,
    steps: Sequence[MaterialMetricStep],
    form_field_names: Iterable[str],
    source_step_refs: frozenset[str],
) -> MaterialMetrics:
    references = _template_references(
        step=step,
        steps=steps,
        form_field_names=form_field_names,
    )
    step_references = [
        reference
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
    ]
    coverage = _structured_prior_coverage(
        step=step,
        steps=steps,
        references=references,
    )
    text_coverage = _text_prior_coverage(
        step=step,
        steps=steps,
        references=references,
    )
    return MaterialMetrics(
        binding_bytes=len(step.question.encode("utf-8")),
        fan_in_width=len(
            {reference.step_ref or reference.head for reference in step_references}
        ),
        structured_field_count=sum(
            1
            for reference in step_references
            if reference.tail.startswith("output.structured.")
        ),
        whole_output_reference_count=sum(
            1
            for reference in step_references
            if reference.tail in {"output.text", "output.structured"}
        ),
        source_duplication_count=sum(
            1
            for reference in step_references
            if (reference.step_ref or reference.head) in source_step_refs
            and reference.tail == "output.text"
        ),
        structured_prior_count=coverage.prior_count,
        structured_prior_ref_count=len(coverage.referenced_prior_refs),
        structured_prior_coverage_ratio=_coverage_ratio(
            referenced_count=len(coverage.referenced_prior_refs),
            prior_count=coverage.prior_count,
        ),
        missing_structured_prior_steps=coverage.missing_prior_refs,
        text_prior_count=text_coverage.prior_count,
        text_prior_ref_count=len(text_coverage.referenced_prior_refs),
        text_prior_coverage_ratio=_coverage_ratio(
            referenced_count=len(text_coverage.referenced_prior_refs),
            prior_count=text_coverage.prior_count,
        ),
        missing_text_prior_steps=text_coverage.missing_prior_refs,
        runtime_input_reference_count=sum(
            1
            for reference in references
            if reference.kind is TemplateReferenceKind.RUNTIME
            and reference.head == "step_input"
            and reference.path_error_code is None
        ),
        form_field_reference_count=sum(
            1
            for reference in references
            if (
                reference.kind is TemplateReferenceKind.FORM_FIELD
                or reference.form_field_name is not None
            )
            and reference.path_error_code is None
        ),
        all_previous_steps_count=(
            1
            if step.input_source == AIBuilderInputSource.ALL_PREVIOUS_STEPS.value
            else 0
        ),
    )


def compute_per_step_material_metrics(
    steps: Sequence[MaterialMetricStep],
    *,
    form_field_names: Iterable[str] = (),
) -> tuple[tuple[int, MaterialMetrics], ...]:
    source_step_refs = _source_surfacing_step_refs(steps)
    return tuple(
        (
            step.step_order,
            _compute_step_material_metrics(
                step=step,
                steps=steps,
                form_field_names=form_field_names,
                source_step_refs=source_step_refs,
            ),
        )
        for step in steps
    )


def _source_surfacing_step_refs(
    steps: Sequence[MaterialMetricStep],
) -> frozenset[str]:
    return frozenset(
        step.step_ref
        for step in steps
        if _is_source_surfacing_metric_step(step)
    )


def _is_source_surfacing_metric_step(step: MaterialMetricStep) -> bool:
    return is_source_surfacing_text(
        input_source=InputSource(step.input_source),
        input_type=InputType(step.input_type),
        output_type=OutputType(step.output_type),
    )


def _template_references(
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
    ]


@dataclass(frozen=True, kw_only=True)
class _StructuredPriorCoverage:
    prior_count: int
    referenced_prior_refs: frozenset[str]
    missing_prior_refs: tuple[str, ...]


def _structured_prior_coverage(
    *,
    step: MaterialMetricStep,
    steps: Sequence[MaterialMetricStep],
    references: Sequence[TemplateReference],
) -> _StructuredPriorCoverage:
    if not step.question.strip():
        return _StructuredPriorCoverage(
            prior_count=0,
            referenced_prior_refs=frozenset(),
            missing_prior_refs=(),
        )

    prior_json_refs = tuple(
        prior.step_ref
        for prior in steps
        if prior.step_order < step.step_order
        and prior.output_type == FlowOutputType.JSON.value
    )
    if not prior_json_refs:
        return _StructuredPriorCoverage(
            prior_count=0,
            referenced_prior_refs=frozenset(),
            missing_prior_refs=(),
        )

    referenced_prior_refs = frozenset(
        reference.step_ref or reference.head
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and reference.tail.startswith("output.structured.")
        and (reference.step_ref or reference.head) in prior_json_refs
    )
    return _StructuredPriorCoverage(
        prior_count=len(prior_json_refs),
        referenced_prior_refs=referenced_prior_refs,
        missing_prior_refs=tuple(
            ref for ref in prior_json_refs if ref not in referenced_prior_refs
        ),
    )


@dataclass(frozen=True, kw_only=True)
class _TextPriorCoverage:
    prior_count: int
    referenced_prior_refs: frozenset[str]
    missing_prior_refs: tuple[str, ...]


def _text_prior_coverage(
    *,
    step: MaterialMetricStep,
    steps: Sequence[MaterialMetricStep],
    references: Sequence[TemplateReference],
) -> _TextPriorCoverage:
    # Empty `all_previous_steps` bindings hide broad fan-in from the UI; count
    # their missing text-prior coverage so final-assembly regressions are visible.
    if (
        not step.question.strip()
        and step.input_source != AIBuilderInputSource.ALL_PREVIOUS_STEPS.value
    ):
        return _TextPriorCoverage(
            prior_count=0,
            referenced_prior_refs=frozenset(),
            missing_prior_refs=(),
        )

    prior_text_refs = tuple(
        prior.step_ref
        for prior in steps
        if prior.step_order < step.step_order
        and prior.output_type == FlowOutputType.TEXT.value
        and not _is_source_surfacing_metric_step(prior)
    )
    if not prior_text_refs:
        return _TextPriorCoverage(
            prior_count=0,
            referenced_prior_refs=frozenset(),
            missing_prior_refs=(),
        )

    referenced_prior_refs = frozenset(
        reference.step_ref or reference.head
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and reference.tail == "output.text"
        and (reference.step_ref or reference.head) in prior_text_refs
    )
    return _TextPriorCoverage(
        prior_count=len(prior_text_refs),
        referenced_prior_refs=referenced_prior_refs,
        missing_prior_refs=tuple(
            ref for ref in prior_text_refs if ref not in referenced_prior_refs
        ),
    )


def _coverage_ratio(*, referenced_count: int, prior_count: int) -> float:
    if prior_count == 0:
        return 1.0
    return referenced_count / prior_count


def _unique_refs(refs: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return tuple(ordered)
