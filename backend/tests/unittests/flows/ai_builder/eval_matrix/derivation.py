"""Prove a golden's composition columns from its spec shape, not from its tags.

A `BuildableGoldenCase` declares which composition columns it intends to cover.
These functions re-derive those columns from the actual `FlowDraftSpecCore`
(step count, FCM-resolved capabilities, template references between steps and
form fields) so a mislabelled golden fails the suite. They also expose the
deterministic buildability gate (the critic preflight, `run_draft_preflight`)
and the form-field resolver the matrix asserts on every golden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from intric.flows.ai_builder.ai_builder_draft_preflight import run_draft_preflight
from intric.flows.ai_builder.ai_builder_form_field_usage import (
    find_unused_form_fields,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_critic_context,
)
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec
from intric.flows.flow_capability_manifest import resolve_capability_for_tuple
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
    referenced_form_fields,
)

from .taxonomy import CompositionColumn

if TYPE_CHECKING:
    from .golden_cases import BuildableGoldenCase

_ADVANCED_CAPABILITY_THRESHOLD = 3
_FORM_FIELDS_CHAIN_MIN_STEPS = 3


def architecture_blockers(
    spec: FlowDraftSpecCore,
    *,
    aggregation_intent: AggregationIntent = "linear",
) -> tuple[str, ...]:
    """Architecture-invariant ids the critic draft preflight reports for this spec.

    Uses an empty conversation: with no user-intent signals only the
    spec-internal architecture invariants can fire, which is exactly the
    "is this draft buildable on its own terms" question the matrix asks. This is
    preflight, not a materializer run. `aggregation_intent` lets comparison
    goldens carry the fan-in semantics the compare invariants expect.
    """
    context = build_conversation_critic_context(
        [], spec, aggregation_intent=aggregation_intent
    )
    result = run_draft_preflight(context)
    return tuple(issue.id for issue in result.architecture_issues)


def unused_form_fields(spec: FlowDraftSpecCore) -> list[str]:
    return find_unused_form_fields(spec)


def _step_templates(step: StepSpec) -> list[str]:
    templates = [step.assistant_spec.instructions]
    for payload in (step.input_bindings, step.output_config):
        if payload is not None:
            templates.append(json.dumps(payload, ensure_ascii=False))
    return templates


def _declared_field_names(spec: FlowDraftSpecCore) -> set[str]:
    return {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }


def _capability_ids(step: StepSpec) -> frozenset[str]:
    pair = resolve_capability_for_tuple(
        input_source=FlowInputSource(step.input_source.value),
        input_type=FlowInputType(step.input_type.value),
        output_type=FlowOutputType(step.output_type.value),
        output_mode=FlowOutputMode(step.output_mode.value),
    )
    if pair is None:
        return frozenset()
    return frozenset(cap.id for cap in pair)


@dataclass(frozen=True)
class _StepReferences:
    """Form-field and prior-step references surfaced by one step's templates."""

    form_fields: set[str]
    earlier_steps: set[str]
    structured_steps: set[str]


def _analyze_step(
    *,
    step: StepSpec,
    index: int,
    step_index: dict[str, int],
    declared_fields: set[str],
) -> _StepReferences:
    form_fields: set[str] = set()
    earlier_steps: set[str] = set()
    structured_steps: set[str] = set()
    for template in _step_templates(step):
        references = analyze_template(
            template,
            step_refs=dict.fromkeys(step_index, 0),
            form_field_names=declared_fields,
        )
        form_fields.update(referenced_form_fields(references))
        for reference in references:
            if reference.kind is not TemplateReferenceKind.STEP:
                continue
            if reference.path_error_code is not None:
                continue
            ref = reference.step_ref or reference.head
            referenced_index = step_index.get(ref)
            if referenced_index is None or referenced_index >= index:
                continue
            earlier_steps.add(ref)
            if reference.tail.startswith("output.structured"):
                structured_steps.add(ref)
    return _StepReferences(
        form_fields=form_fields,
        earlier_steps=earlier_steps,
        structured_steps=structured_steps,
    )


def derive_composition_columns(
    case: "BuildableGoldenCase",
) -> frozenset[CompositionColumn]:
    spec = case.spec
    steps = spec.steps
    declared_fields = _declared_field_names(spec)
    step_index = {step.plan_step_ref: index for index, step in enumerate(steps)}
    analyses = [
        _analyze_step(
            step=step,
            index=index,
            step_index=step_index,
            declared_fields=declared_fields,
        )
        for index, step in enumerate(steps)
    ]

    columns: set[CompositionColumn] = set()

    if len(steps) == 1:
        columns.add(CompositionColumn.BASIC_SINGLE_STEP)

    # "Three distinct capabilities composed": needs both the composition (>= 3
    # steps) and the breadth (>= 3 distinct FCM capability ids). Either alone is
    # too weak — a two-step flow reaches three flattened ids just by touching
    # two input types plus the ubiquitous pass-through mode.
    if len(steps) >= _ADVANCED_CAPABILITY_THRESHOLD:
        distinct_capabilities: set[str] = set()
        for step in steps:
            distinct_capabilities |= _capability_ids(step)
        if len(distinct_capabilities) >= _ADVANCED_CAPABILITY_THRESHOLD:
            columns.add(CompositionColumn.ADVANCED_MULTI_CAPABILITY)

    if declared_fields and analyses:
        first_step_uses_fields = bool(analyses[0].form_fields)
        later_consumes_prior = any(a.earlier_steps for a in analyses[1:])
        later_uses_form_field = any(a.form_fields for a in analyses[1:])
        # The chain's defining move: a later step that reads BOTH a flow-scope
        # form field AND an earlier step's output, proving the flow-scope vs
        # step-scope distinction rather than two independent references.
        has_combining_step = any(
            a.form_fields and a.earlier_steps for a in analyses[1:]
        )
        if (
            len(steps) >= _FORM_FIELDS_CHAIN_MIN_STEPS
            and first_step_uses_fields
            and later_consumes_prior
            and has_combining_step
        ):
            columns.add(CompositionColumn.FORM_FIELDS_CHAIN)
        elif first_step_uses_fields and not later_uses_form_field:
            columns.add(CompositionColumn.FORM_FIELDS_DECLARE_ONLY)

    for index, step in enumerate(steps):
        if step.output_type is not FlowOutputType.JSON:
            continue
        if any(
            step.plan_step_ref in analysis.structured_steps
            for analysis in analyses[index + 1 :]
        ):
            columns.add(CompositionColumn.JSON_IN_JSON_OUT_PIPE)
            break

    for analysis in analyses:
        if analysis.form_fields and len(analysis.earlier_steps) >= 2:
            columns.add(CompositionColumn.ALL_STEPS_MULTI_REFERENCE)
            break

    if case.via_edit:
        columns.add(CompositionColumn.EDIT_PATH)

    return frozenset(columns)
