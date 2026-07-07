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
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    SemanticStepIntent,
)
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

_DOCUMENT_OUTPUT_TYPES = frozenset({OutputType.PDF, OutputType.DOCX})

PlannedStepRole = Literal["reader", "transform", "body_writer", "renderer"]
UnderlagChannel = Literal[
    "flow_input", "implicit_previous", "field_refs", "text_anchor"
]


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
    document_delivery_mode: DocumentDeliveryMode = "not_applicable"
    form_field_refs: tuple[str, ...] = ()
    previous_field_refs: tuple[PreviousFieldRef, ...] = ()
    previous_output_refs: tuple[PreviousOutputRef, ...] = ()
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
    plan = _assemble_linear_create_intent(
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


def _assemble_linear_create_intent(
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
        or not intent.steps
    ):
        return None
    if runtime_input_type not in {InputType.TEXT, InputType.JSON}:
        return None
    document_artifact_requested = final_output_type in _DOCUMENT_OUTPUT_TYPES
    if (
        final_output_type
        not in {OutputType.TEXT, OutputType.JSON} | _DOCUMENT_OUTPUT_TYPES
    ):
        return None
    if final_output_mode == OutputMode.TEMPLATE_FILL:
        return None
    semantic_output_mode = OutputMode.PASS_THROUGH
    if (
        not document_artifact_requested
        and (final_output_mode or OutputMode.PASS_THROUGH) != OutputMode.PASS_THROUGH
    ):
        return None

    terminal_semantic_output_type = (
        OutputType.TEXT if document_artifact_requested else final_output_type
    )
    form_field_names = {field.name for field in form_fields}
    placed_form_fields: set[str] = set()
    planned_steps: list[PlannedStep] = []
    previous_output_type: OutputType | None = None
    for index, semantic_step in enumerate(intent.steps):
        if not _previous_refs_are_immediate(semantic_step, step_index=index):
            return None
        step_output_type = _linear_step_output_type(
            output_type=semantic_step.output_type,
            output_fields=semantic_step.output_fields,
            final_output_type=terminal_semantic_output_type,
            is_terminal=index == len(intent.steps) - 1,
        )
        if step_output_type is None:
            return None
        input_source = (
            InputSource.FLOW_INPUT if index == 0 else InputSource.PREVIOUS_STEP
        )
        input_type = _linear_step_input_type(
            step_index=index,
            runtime_input_type=runtime_input_type,
            previous_output_type=previous_output_type,
            output_type=step_output_type,
            has_explicit_previous_refs=bool(
                semantic_step.uses_previous_fields
                or semantic_step.uses_previous_outputs
            ),
        )
        planned_step = PlannedStep(
            role=_linear_step_role(
                output_type=step_output_type,
                is_terminal=index == len(intent.steps) - 1,
                document_artifact_requested=document_artifact_requested,
            ),
            name=semantic_step.name,
            instructions=semantic_step.instructions,
            input_source=input_source,
            input_type=input_type,
            output_type=step_output_type,
            output_mode=semantic_output_mode,
            underlag_channel=_linear_underlag_channel(
                step_index=index,
                previous_field_refs=semantic_step.uses_previous_fields,
                previous_output_refs=semantic_step.uses_previous_outputs,
            ),
            form_field_refs=tuple(semantic_step.uses_form_fields),
            previous_field_refs=tuple(semantic_step.uses_previous_fields),
            previous_output_refs=tuple(semantic_step.uses_previous_outputs),
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
        planned_steps.append(planned_step)
        placed_form_fields.update(planned_step.form_field_refs)
        previous_output_type = step_output_type

    if placed_form_fields != form_field_names:
        return None
    if document_artifact_requested:
        renderer_step = _render_verbatim_step(
            output_type=final_output_type,
            body_step_name=planned_steps[-1].name,
        )
        if not _capability_tuple_is_supported(renderer_step):
            return None
        planned_steps.append(renderer_step)
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=tuple(form_fields),
        steps=tuple(planned_steps),
        ui_language=ui_language,
    )


def _previous_refs_are_immediate(
    semantic_step: SemanticStepIntent,
    *,
    step_index: int,
) -> bool:
    if step_index == 0:
        expected_from_step = 0
    else:
        expected_from_step = step_index
    if semantic_step.uses_previous_fields and semantic_step.uses_previous_outputs:
        return False
    return all(
        ref.from_step == expected_from_step
        for ref in (
            *semantic_step.uses_previous_fields,
            *semantic_step.uses_previous_outputs,
        )
    )


def _linear_step_output_type(
    *,
    output_type: OutputType | None,
    output_fields: Sequence[StructuredFieldDraft] | None,
    final_output_type: OutputType,
    is_terminal: bool,
) -> OutputType | None:
    step_output_type = output_type
    if step_output_type is None:
        if output_fields:
            step_output_type = OutputType.JSON
        elif is_terminal:
            step_output_type = final_output_type
        else:
            step_output_type = OutputType.TEXT
    if output_fields and step_output_type != OutputType.JSON:
        return None
    if is_terminal and step_output_type != final_output_type:
        return None
    return step_output_type


def _linear_step_input_type(
    *,
    step_index: int,
    runtime_input_type: InputType,
    previous_output_type: OutputType | None,
    output_type: OutputType,
    has_explicit_previous_refs: bool,
) -> InputType:
    if step_index == 0:
        return runtime_input_type
    if previous_output_type == OutputType.JSON:
        if output_type == OutputType.TEXT and has_explicit_previous_refs:
            return InputType.TEXT
        return InputType.JSON
    return InputType.TEXT


def _linear_step_role(
    *,
    output_type: OutputType,
    is_terminal: bool,
    document_artifact_requested: bool,
) -> PlannedStepRole:
    if is_terminal and document_artifact_requested:
        return "body_writer"
    if output_type == OutputType.JSON:
        return "reader"
    return "transform"


def _linear_underlag_channel(
    *,
    step_index: int,
    previous_field_refs: Sequence[PreviousFieldRef],
    previous_output_refs: Sequence[PreviousOutputRef],
) -> UnderlagChannel:
    if step_index == 0:
        return "flow_input"
    if previous_field_refs:
        return "field_refs"
    if previous_output_refs:
        return "text_anchor"
    return "implicit_previous"


def _render_verbatim_step(
    *,
    output_type: OutputType,
    body_step_name: str,
) -> PlannedStep:
    return PlannedStep(
        role="renderer",
        name=f"Render {body_step_name}",
        instructions="Render the final document.",
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=output_type,
        output_mode=OutputMode.RENDER_VERBATIM,
        underlag_channel="implicit_previous",
        document_delivery_mode="generated",
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
    document_body_writer_step_refs = tuple(
        compiled_step.plan_step_ref
        for planned_step, compiled_step in zip(plan.steps, compiled_steps, strict=True)
        if planned_step.role == "body_writer"
    )
    return FlowDraftSpecCore(
        flow_name=normalize_flow_name(plan.flow_name),
        flow_description=plan.flow_description,
        steps=compiled_steps,
        form_fields=list(plan.form_fields) or None,
        document_body_writer_step_refs=document_body_writer_step_refs or None,
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
        uses_previous_fields=list(step.previous_field_refs),
        uses_previous_outputs=list(step.previous_output_refs),
        output_fields=list(step.output_fields),
        document_delivery_mode=step.document_delivery_mode,
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )
