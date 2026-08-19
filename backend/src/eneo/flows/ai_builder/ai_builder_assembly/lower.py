from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_assembly.document_report import (
    bind_document_report_compose_inputs,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
)
from eneo.flows.ai_builder.ai_builder_domain_models import LintSeverity, LintWarning
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_new_step_draft,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    apply_terminal_output_schema,
    source_capture_fields_by_step_index,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_step_citation_mode,
    supports_inline_inref_citation,
)
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputMode,
    StepSpec,
)
from eneo.flows.source_identity import without_runtime_source_identity_draft_fields
from eneo.main.logging import get_logger

logger = get_logger(__name__)


def lower_assembly_plan(
    plan: FlowAssemblyPlan,
    *,
    field_diagnostics: list[LintWarning] | None = None,
) -> FlowDraftSpecCore:
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
    citation_warning: LintWarning | None = None
    flow_supports_inline_citations = supports_inline_inref_citation(
        output_type=plan.steps[-1].output_type,
        output_mode=plan.steps[-1].output_mode,
    )
    for index, (planned_step, step_draft) in enumerate(
        zip(plan.steps, step_drafts, strict=True)
    ):
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
        if planned_step.output_mode != compiled_step.output_mode:
            raise ValueError("Planned step output_mode diverged during lowering.")
        compiled_step, citation_change = normalize_ai_builder_step_citation_mode(
            compiled_step,
            ui_language=plan.ui_language,
            flow_supports_inline_citations=flow_supports_inline_citations,
        )
        if citation_change is not None and citation_warning is None:
            citation_warning = LintWarning(
                step_ref=compiled_step.plan_step_ref,
                code=citation_change.code,
                message=citation_change.message,
                severity=LintSeverity(citation_change.severity),
            )
        if planned_step.output_mode == OutputMode.COMPOSE_TEXT:
            compiled_step = bind_document_report_compose_inputs(
                step=compiled_step,
                prior_steps=compiled_steps,
                form_field_refs=planned_step.form_field_refs,
                requested_output_section_contracts=(
                    plan.requested_output_section_contracts
                ),
                document_report_section_source=plan.document_report_section_source,
                ui_language=plan.ui_language,
            )
        compiled_steps.append(compiled_step)
    if citation_warning is not None and field_diagnostics is not None:
        field_diagnostics.append(citation_warning)
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
        flow_name=flow_name,
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
        uses_previous_outputs=list(step.previous_output_refs),
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
