from __future__ import annotations

import logging

from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_new_step_draft,
    derive_new_step_output_mode,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.ai_builder.ai_builder_source_material import (
    SourceMaterialBindingStatus,
    iter_compiled_source_material_boundaries,
    source_material_binding_status,
    source_material_bindings_for_boundary,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    apply_terminal_output_schema,
    source_capture_fields_by_step_index,
)
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputType,
    StepSpec,
)

logger = logging.getLogger(__name__)


def lower_assembly_plan(plan: FlowAssemblyPlan) -> FlowDraftSpecCore:
    flow_name = normalize_flow_name(plan.flow_name)
    step_drafts: list[NewStepDraft] = []
    for index, planned_step in enumerate(plan.steps):
        emit_output_fields = (
            plan.terminal_output_schema is None or index != len(plan.steps) - 1
        )
        if not emit_output_fields and planned_step.output_fields:
            logger.info(
                "ai_builder_terminal_output_fields_suppressed_by_schema",
                extra={
                    "step_index": index + 1,
                    "step_name": planned_step.name,
                    "field_names": [field.name for field in planned_step.output_fields],
                },
            )
        step_drafts.append(
            _new_step_draft_from_planned_step(
                planned_step,
                emit_output_fields=emit_output_fields,
            )
        )
    form_fields = list(plan.form_fields)
    source_capture_fields_by_index = source_capture_fields_by_step_index(
        steps=step_drafts,
        terminal_output_schema=plan.terminal_output_schema,
    )
    compiled_steps: list[StepSpec] = []
    for index, (planned_step, step_draft) in enumerate(
        zip(plan.steps, step_drafts, strict=True)
    ):
        if planned_step.output_mode != derive_new_step_output_mode(step_draft):
            raise ValueError("Planned step output_mode diverged during lowering.")
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
    compiled_steps = _complete_source_material_boundaries(
        flow_name=flow_name,
        flow_description=plan.flow_description,
        steps=compiled_steps,
        form_fields=form_fields,
        ui_language=plan.ui_language,
    )
    document_body_writer_step_refs = tuple(
        compiled_step.plan_step_ref
        for planned_step, compiled_step in zip(plan.steps, compiled_steps, strict=True)
        if planned_step.role == "body_writer"
    )
    return FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description=plan.flow_description,
        steps=compiled_steps,
        form_fields=form_fields or None,
        document_body_writer_step_refs=document_body_writer_step_refs or None,
    )


def _complete_source_material_boundaries(
    *,
    flow_name: str,
    flow_description: str,
    steps: list[StepSpec],
    form_fields: list[FormFieldSpec],
    ui_language: str | None,
) -> list[StepSpec]:
    spec = FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description=flow_description,
        steps=steps,
        form_fields=form_fields or None,
    )
    updated_steps = list(steps)
    mutated = False
    for boundary in iter_compiled_source_material_boundaries(spec):
        if (
            source_material_binding_status(boundary)
            is not SourceMaterialBindingStatus.NEEDS_COMPLETION
        ):
            continue
        updated_steps[boundary.step_order - 1] = boundary.step.model_copy(
            update={
                "input_type": InputType.TEXT,
                "input_bindings": source_material_bindings_for_boundary(
                    boundary,
                    ui_language=ui_language,
                ),
                "input_contract": None,
            }
        )
        mutated = True
    return updated_steps if mutated else steps


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
        output_fields=list(step.output_fields) if emit_output_fields else None,
        document_delivery_mode=step.document_delivery_mode,
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )
