from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_new_step_draft,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    apply_terminal_output_schema,
    source_capture_fields_by_step_index,
)
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec


def lower_assembly_plan(plan: FlowAssemblyPlan) -> FlowDraftSpecCore:
    step_drafts = [
        _new_step_draft_from_planned_step(
            planned_step,
            emit_output_fields=(
                plan.terminal_output_schema is None or index != len(plan.steps) - 1
            ),
        )
        for index, planned_step in enumerate(plan.steps)
    ]
    form_fields = list(plan.form_fields)
    source_capture_fields_by_index = source_capture_fields_by_step_index(
        steps=step_drafts,
        terminal_output_schema=plan.terminal_output_schema,
    )
    compiled_steps: list[StepSpec] = []
    for index, step_draft in enumerate(step_drafts):
        compiled_steps.append(
            compile_new_step_draft(
                step_draft=step_draft,
                plan_step_ref=make_plan_step_ref(index),
                prior_steps=compiled_steps,
                source_capture_fields=source_capture_fields_by_index.get(index, ()),
                ui_language=plan.ui_language,
            )
        )
    compiled_steps = apply_terminal_output_schema(
        compiled_steps,
        terminal_output_schema=plan.terminal_output_schema,
    )
    document_body_writer_step_refs = tuple(
        compiled_step.plan_step_ref
        for planned_step, compiled_step in zip(plan.steps, compiled_steps, strict=True)
        if planned_step.role == "body_writer"
    )
    return FlowDraftSpecCore(
        flow_name=normalize_flow_name(plan.flow_name),
        flow_description=plan.flow_description,
        steps=compiled_steps,
        form_fields=form_fields or None,
        document_body_writer_step_refs=document_body_writer_step_refs or None,
    )


def _new_step_draft_from_planned_step(
    step: PlannedStep,
    *,
    emit_output_fields: bool,
) -> NewStepDraft:
    return NewStepDraft(
        name=step.name,
        instructions=step.instructions,
        input_source=step.input_source,
        input_type=step.input_type,
        output_type=step.output_type,
        model_ref=step.model_ref,
        knowledge_refs=list(step.knowledge_refs),
        mcp_server_refs=list(step.mcp_server_refs),
        mcp_tool_refs=list(step.mcp_tool_refs),
        runtime_required=step.runtime_required,
        runtime_max_files=step.runtime_max_files,
        uses_form_fields=list(step.form_field_refs),
        uses_previous_fields=list(step.previous_field_refs),
        uses_previous_outputs=list(step.previous_output_refs),
        output_fields=list(step.output_fields) if emit_output_fields else None,
        document_delivery_mode=step.document_delivery_mode,
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )
