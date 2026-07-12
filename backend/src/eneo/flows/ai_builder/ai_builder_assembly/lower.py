from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_new_step_draft,
    derive_new_step_output_mode,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
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
    OutputMode,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import SourceRefBinding
from eneo.flows.source_identity import without_runtime_source_identity_draft_fields

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
        compiled_step = compile_new_step_draft(
            step_draft=step_draft,
            plan_step_ref=make_plan_step_ref(index),
            prior_steps=compiled_steps,
            source_capture_fields=source_capture_fields_by_index.get(index, ()),
            assistant_output_fields=_assistant_output_fields_for_planned_step(
                planned_step,
                is_terminal_schema_step=(
                    plan.terminal_output_schema is not None
                    and index == len(plan.steps) - 1
                ),
            ),
            ui_language=plan.ui_language,
        )
        if planned_step.output_mode == OutputMode.COMPOSE_TEXT:
            compiled_step = _with_compose_source_refs(
                step=compiled_step,
                prior_steps=compiled_steps,
                ui_language=plan.ui_language,
            )
        compiled_steps.append(compiled_step)
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


def _with_compose_source_refs(
    *,
    step: StepSpec,
    prior_steps: list[StepSpec],
    ui_language: str | None,
) -> StepSpec:
    section_step, section_array = _find_compose_section_source(prior_steps)
    if section_step is None or section_array is None:
        return step

    source_refs: list[dict[str, object]] = [
        SourceRefBinding(
            step_ref=section_step.plan_step_ref,
            output="structured",
            field_path=(section_array,),
            item_template=_compose_section_item_template(ui_language),
        ).binding_payload()
    ]
    overview_step = _find_compose_overview_source(prior_steps)
    question = _compose_report_title_question(
        overview_step=overview_step,
        ui_language=ui_language,
    )
    if overview_step is not None:
        source_refs.append(
            SourceRefBinding(
                step_ref=overview_step.plan_step_ref,
                output="structured",
                field_path=("overall_overview",),
                label=_compose_overview_label(ui_language),
            ).binding_payload()
        )
    return step.model_copy(
        update={
            "input_bindings": {
                "question": question,
                "source_refs": source_refs,
            },
            "input_contract": None,
        }
    )


def _find_compose_section_source(
    prior_steps: list[StepSpec],
) -> tuple[StepSpec | None, str | None]:
    for prior_step in reversed(prior_steps):
        properties = _schema_properties(prior_step.output_contract)
        for field_name, schema in properties.items():
            item_properties = _array_item_properties(schema)
            if {"section_title", "section_body", "source_label"}.issubset(
                item_properties
            ):
                return prior_step, field_name
    return None, None


def _find_compose_overview_source(prior_steps: list[StepSpec]) -> StepSpec | None:
    for prior_step in reversed(prior_steps):
        properties = _schema_properties(prior_step.output_contract)
        if {"report_title", "overall_overview"}.issubset(properties):
            return prior_step
    return None


def _schema_properties(schema: object) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    typed_schema = cast(Mapping[str, object], schema)
    raw_properties = typed_schema.get("properties")
    if not isinstance(raw_properties, Mapping):
        return {}
    properties = cast(Mapping[object, object], raw_properties)
    return {
        key: value
        for key, value in properties.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


def _array_item_properties(schema: object) -> set[str]:
    if not isinstance(schema, Mapping):
        return set()
    typed_schema = cast(Mapping[str, object], schema)
    raw_type = typed_schema.get("type")
    if raw_type != "array":
        return set()
    return set(_schema_properties(typed_schema.get("items")))


def _compose_report_title_question(
    *,
    overview_step: StepSpec | None,
    ui_language: str | None,
) -> str:
    if overview_step is not None:
        return (
            f"# {{{{ {overview_step.plan_step_ref}.output.structured.report_title }}}}"
        )
    return "# Source report" if ui_language == "en" else "# Rapport per källa"


def _compose_section_item_template(ui_language: str | None) -> str:
    source_label = "Source" if ui_language == "en" else "Källa"
    return (
        f"## {{section_title}}\n\n{{section_body}}\n\n{source_label}: {{source_label}}"
    )


def _compose_overview_label(ui_language: str | None) -> str:
    return "Overall overview" if ui_language == "en" else "Samlad översikt"


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
        output_mode=step.output_mode,
        output_type=step.output_type,
        model_ref=step.model_ref,
        knowledge_refs=list(step.knowledge_refs),
        runtime_required=step.runtime_required,
        runtime_max_files=step.runtime_max_files,
        runtime_input_execution_mode=step.runtime_input_execution_mode,
        previous_item_map_enabled=step.previous_item_map_enabled,
        uses_form_fields=list(step.form_field_refs),
        uses_previous_fields=list(step.previous_field_refs),
        output_fields=list(step.output_fields) if emit_output_fields else None,
        document_delivery_mode=step.document_delivery_mode,
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )


def _assistant_output_fields_for_planned_step(
    step: PlannedStep,
    *,
    is_terminal_schema_step: bool,
) -> list[StructuredFieldDraft] | None:
    if is_terminal_schema_step:
        return []
    if (
        step.runtime_input_execution_mode != "per_source"
        and not step.previous_item_map_enabled
    ):
        return None
    return without_runtime_source_identity_draft_fields(list(step.output_fields))
