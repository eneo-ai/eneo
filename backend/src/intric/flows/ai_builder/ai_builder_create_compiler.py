from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
)
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    FlowCreateDraft,
)
from intric.flows.ai_builder.ai_builder_new_step_compiler import compile_new_step_draft
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.flow_authoring_name import normalize_flow_name
from intric.flows.flow_authoring_runtime_input import (
    normalize_flow_draft_runtime_inputs,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    StepSpec,
)


def compile_create_draft(
    draft: FlowCreateDraft,
    *,
    aggregation_intent: AggregationIntent = "linear",
) -> FlowDraftSpecCore:
    draft = normalize_create_draft_mechanics(
        draft,
        aggregation_intent=aggregation_intent,
    )
    compiled_steps: list[StepSpec] = []
    for index, step_draft in enumerate(draft.steps):
        compiled_steps.append(
            compile_new_step_draft(
                step_draft=step_draft,
                step_index=index,
                prior_steps=compiled_steps,
            )
        )

    compiled = FlowDraftSpecCore(
        flow_name=normalize_flow_name(draft.flow_name),
        flow_description=draft.flow_description or "",
        steps=compiled_steps,
        form_fields=[_compile_form_field(field) for field in draft.form_fields] or None,
    )
    return normalize_flow_draft_runtime_inputs(compiled)


def _compile_form_field(field: CreateFormFieldDraft) -> FormFieldSpec:
    return FormFieldSpec(
        name=field.variable_name,
        type=field.field_type,
        label=field.label,
        required=field.required,
        options=list(field.options) or None,
    )
