from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    SourceCaptureField,
    compile_new_step_draft,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import CreateFlowIntent
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_capability_manifest import resolve_capability_for_tuple
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.json_types import JsonObject

PlannedStepRole = Literal["reader", "transform"]
UnderlagChannel = Literal["flow_input"]


@dataclass(frozen=True, slots=True)
class PlannedStep:
    role: PlannedStepRole
    name: str
    instructions: str
    input_source: InputSource
    input_type: InputType
    output_type: OutputType
    output_mode: OutputMode
    underlag_channel: UnderlagChannel
    form_field_refs: tuple[str, ...] = ()
    output_fields: tuple[StructuredFieldDraft, ...] = ()
    model_ref: str | None = None
    knowledge_refs: tuple[str, ...] = ()
    mcp_server_refs: tuple[str, ...] = ()
    mcp_tool_refs: tuple[str, ...] = ()
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None


@dataclass(frozen=True, slots=True)
class FlowAssemblyPlan:
    flow_name: str
    flow_description: str
    form_fields: tuple[FormFieldSpec, ...]
    steps: tuple[PlannedStep, ...]
    ui_language: str | None


def try_compile_create_intent_with_assembly(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    form_fields: Sequence[FormFieldSpec],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: str,
    terminal_output_schema: JsonObject | None,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    ui_language: str | None,
) -> FlowDraftSpecCore | None:
    plan = _assemble_single_step_create_intent(
        intent,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        form_fields=form_fields,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        aggregation_intent=aggregation_intent,
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=source_reader_required_fields,
        ui_language=ui_language,
    )
    if plan is None:
        return None
    return _lower_assembly_plan(plan)


def _assemble_single_step_create_intent(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    form_fields: Sequence[FormFieldSpec],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: str,
    terminal_output_schema: JsonObject | None,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    ui_language: str | None,
) -> FlowAssemblyPlan | None:
    if (
        pattern_ids
        or chain_steps
        or aggregation_intent != "linear"
        or terminal_output_schema is not None
        or source_reader_required_fields
        or len(intent.steps) != 1
    ):
        return None
    if runtime_input_type not in {InputType.TEXT, InputType.JSON}:
        return None
    if final_output_type not in {OutputType.TEXT, OutputType.JSON}:
        return None
    output_mode = final_output_mode or OutputMode.PASS_THROUGH
    if output_mode != OutputMode.PASS_THROUGH:
        return None

    semantic_step = intent.steps[0]
    if semantic_step.uses_previous_fields or semantic_step.uses_previous_outputs:
        return None
    if (
        semantic_step.output_type is not None
        and semantic_step.output_type != final_output_type
    ):
        return None
    if semantic_step.output_fields and final_output_type != OutputType.JSON:
        return None

    placed_form_fields = tuple(semantic_step.uses_form_fields)
    form_field_names = {field.name for field in form_fields}
    if set(placed_form_fields) != form_field_names:
        return None

    planned_step = PlannedStep(
        role="reader" if final_output_type == OutputType.JSON else "transform",
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        input_source=InputSource.FLOW_INPUT,
        input_type=runtime_input_type,
        output_type=final_output_type,
        output_mode=output_mode,
        underlag_channel="flow_input",
        form_field_refs=placed_form_fields,
        output_fields=tuple(semantic_step.output_fields or ()),
        model_ref=semantic_step.model_ref,
        knowledge_refs=tuple(semantic_step.knowledge_refs),
        mcp_server_refs=tuple(semantic_step.mcp_server_refs),
        mcp_tool_refs=tuple(semantic_step.mcp_tool_refs),
        citations_requested=semantic_step.citations_requested,
        review_mode=semantic_step.review_mode,
    )
    if not _capability_tuple_is_supported(planned_step):
        return None
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=tuple(form_fields),
        steps=(planned_step,),
        ui_language=ui_language,
    )


def _capability_tuple_is_supported(step: PlannedStep) -> bool:
    return (
        resolve_capability_for_tuple(
            input_source=FlowInputSource(step.input_source.value),
            input_type=FlowInputType(step.input_type.value),
            output_type=FlowOutputType(step.output_type.value),
            output_mode=FlowOutputMode(step.output_mode.value),
        )
        is not None
    )


def _lower_assembly_plan(plan: FlowAssemblyPlan) -> FlowDraftSpecCore:
    compiled_steps: list[StepSpec] = []
    for index, planned_step in enumerate(plan.steps):
        compiled_steps.append(
            compile_new_step_draft(
                step_draft=_new_step_draft_from_planned_step(planned_step),
                plan_step_ref=make_plan_step_ref(index),
                prior_steps=compiled_steps,
                ui_language=plan.ui_language,
            )
        )
    return FlowDraftSpecCore(
        flow_name=normalize_flow_name(plan.flow_name),
        flow_description=plan.flow_description,
        steps=compiled_steps,
        form_fields=list(plan.form_fields) or None,
    )


def _new_step_draft_from_planned_step(step: PlannedStep) -> NewStepDraft:
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
        runtime_required=False,
        uses_form_fields=list(step.form_field_refs),
        output_fields=list(step.output_fields),
        document_delivery_mode="not_applicable",
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )
