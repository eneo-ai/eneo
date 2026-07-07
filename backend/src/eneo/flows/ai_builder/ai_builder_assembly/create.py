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
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    apply_terminal_output_schema,
    clear_terminal_schema_output_fields,
    complete_source_reader_contracts,
    drop_source_contract_shadow_form_fields,
    log_dropped_source_contract_shadow_fields,
    source_capture_fields_by_step_index,
)
from eneo.flows.ai_builder.pattern_registry import (
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    TERMINAL_ARTIFACT_STEP,
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
_SOURCE_INPUT_TYPES = frozenset(
    {
        InputType.AUDIO,
        InputType.DOCUMENT,
        InputType.FILE,
        InputType.JSON,
        InputType.TEXT,
    }
)
_FILE_INPUT_TYPES = frozenset({InputType.DOCUMENT, InputType.FILE})
_AUDIO_TRANSCRIPTION_PATTERN_ID = "audio_transcription"
_AUDIO_ARTIFACT_PATTERN_ID = "audio_to_artifact_report"
_AUDIO_PATTERN_IDS = frozenset(
    {_AUDIO_TRANSCRIPTION_PATTERN_ID, _AUDIO_ARTIFACT_PATTERN_ID}
)
_AUDIO_PATTERN_CHAIN_STEPS = frozenset(
    {FLOW_INPUT_AUDIO_TRANSCRIPTION, TERMINAL_ARTIFACT_STEP}
)

PlannedStepRole = Literal[
    "reader", "transform", "body_writer", "renderer", "transcription"
]
UnderlagChannel = Literal[
    "flow_input", "implicit_previous", "field_refs", "text_anchor", "fan_in"
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
    runtime_required: bool = False
    runtime_max_files: int | None = None
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
    terminal_output_schema: JsonObject | None
    source_reader_required_fields: tuple[SourceCaptureField, ...]
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
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> FlowDraftSpecCore | None:
    plan = _assemble_create_intent(
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
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )
    if plan is None:
        return None
    return _lower_assembly_plan(plan)


def _assemble_create_intent(
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
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> FlowAssemblyPlan | None:
    if (
        not _architecture_hints_are_supported(
            runtime_input_type=runtime_input_type,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
        )
        or aggregation_intent not in {"linear", "aggregate", "compare"}
        or not intent.steps
    ):
        return None
    if runtime_input_type not in _SOURCE_INPUT_TYPES:
        return None
    if runtime_input_type == InputType.AUDIO and aggregation_intent != "linear":
        return None
    document_artifact_requested = final_output_type in _DOCUMENT_OUTPUT_TYPES
    if (
        final_output_type
        not in {OutputType.TEXT, OutputType.JSON} | _DOCUMENT_OUTPUT_TYPES
    ):
        return None
    if final_output_mode == OutputMode.TEMPLATE_FILL:
        return None
    if terminal_output_schema is not None and (
        document_artifact_requested or final_output_type != OutputType.JSON
    ):
        return None
    if aggregation_intent != "linear" and (
        terminal_output_schema is not None or final_output_type == OutputType.JSON
    ):
        return None
    if _is_pure_audio_transcription_request(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
    ):
        if source_reader_required_fields:
            return None
        return _assemble_pure_audio_transcription(
            intent,
            form_fields=form_fields,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
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
    source_prefix_step_count = 0
    if runtime_input_type == InputType.AUDIO:
        transcription_step = _fixed_audio_transcription_step(
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
        if not _capability_tuple_is_supported(transcription_step):
            return None
        planned_steps.append(transcription_step)
        previous_output_type = OutputType.TEXT
        source_prefix_step_count = 1
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
        if (
            index == 0
            and runtime_input_type in _FILE_INPUT_TYPES
            and step_output_type != OutputType.JSON
        ):
            return None
        input_source = _linear_step_input_source(
            step_index=index,
            semantic_step_count=len(intent.steps),
            aggregation_intent=aggregation_intent,
            has_source_prefix=source_prefix_step_count > 0,
        )
        if input_source == InputSource.ALL_PREVIOUS_STEPS and (
            semantic_step.uses_form_fields
            or semantic_step.uses_previous_fields
            or semantic_step.uses_previous_outputs
        ):
            return None
        input_type = _linear_step_input_type(
            input_source=input_source,
            runtime_input_type=runtime_input_type,
            previous_output_type=previous_output_type,
            output_type=step_output_type,
            has_explicit_previous_refs=bool(
                semantic_step.uses_previous_fields
                or semantic_step.uses_previous_outputs
            ),
        )
        previous_field_refs = _offset_previous_field_refs(
            semantic_step.uses_previous_fields,
            compiled_step_offset=source_prefix_step_count,
        )
        previous_output_refs = _offset_previous_output_refs(
            semantic_step.uses_previous_outputs,
            compiled_step_offset=source_prefix_step_count,
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
                input_source=input_source,
                previous_field_refs=previous_field_refs,
                previous_output_refs=previous_output_refs,
            ),
            runtime_required=(
                index == 0
                and runtime_input_type in _FILE_INPUT_TYPES
                and runtime_required
            ),
            runtime_max_files=(
                runtime_max_files
                if index == 0 and runtime_input_type in _FILE_INPUT_TYPES
                else None
            ),
            form_field_refs=tuple(semantic_step.uses_form_fields),
            previous_field_refs=previous_field_refs,
            previous_output_refs=previous_output_refs,
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
    if source_reader_required_fields and not any(
        _planned_step_is_source_reader(step) for step in planned_steps
    ):
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
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=source_reader_required_fields,
        ui_language=ui_language,
    )


def _architecture_hints_are_supported(
    *,
    runtime_input_type: InputType,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    if not pattern_ids and not chain_steps:
        return True
    if runtime_input_type != InputType.AUDIO:
        return False
    return set(pattern_ids) <= _AUDIO_PATTERN_IDS and set(chain_steps) <= set(
        _AUDIO_PATTERN_CHAIN_STEPS
    )


def _is_pure_audio_transcription_request(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
) -> bool:
    return (
        runtime_input_type == InputType.AUDIO
        and final_output_type == OutputType.TEXT
        and (
            final_output_mode == OutputMode.TRANSCRIBE_ONLY
            or _AUDIO_TRANSCRIPTION_PATTERN_ID in pattern_ids
        )
    )


def _assemble_pure_audio_transcription(
    intent: CreateFlowIntent,
    *,
    form_fields: Sequence[FormFieldSpec],
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> FlowAssemblyPlan | None:
    if len(intent.steps) != 1 or form_fields:
        return None
    semantic_step = intent.steps[0]
    if (
        semantic_step.output_fields
        or semantic_step.uses_form_fields
        or semantic_step.uses_previous_fields
        or semantic_step.uses_previous_outputs
        or semantic_step.output_type not in {None, OutputType.TEXT}
    ):
        return None
    planned_step = _fixed_audio_transcription_step(
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
        review_mode=semantic_step.review_mode,
    )
    if not _capability_tuple_is_supported(planned_step):
        return None
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=(),
        steps=(planned_step,),
        terminal_output_schema=None,
        source_reader_required_fields=(),
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
    input_source: InputSource,
    runtime_input_type: InputType,
    previous_output_type: OutputType | None,
    output_type: OutputType,
    has_explicit_previous_refs: bool,
) -> InputType:
    if input_source == InputSource.FLOW_INPUT:
        return runtime_input_type
    if input_source == InputSource.ALL_PREVIOUS_STEPS:
        return InputType.TEXT
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


def _linear_step_input_source(
    *,
    step_index: int,
    semantic_step_count: int,
    aggregation_intent: str,
    has_source_prefix: bool,
) -> InputSource:
    if step_index == 0 and not has_source_prefix:
        return InputSource.FLOW_INPUT
    if (
        aggregation_intent in {"aggregate", "compare"}
        and step_index == semantic_step_count - 1
    ):
        return InputSource.ALL_PREVIOUS_STEPS
    return InputSource.PREVIOUS_STEP


def _linear_underlag_channel(
    *,
    input_source: InputSource,
    previous_field_refs: Sequence[PreviousFieldRef],
    previous_output_refs: Sequence[PreviousOutputRef],
) -> UnderlagChannel:
    if input_source == InputSource.FLOW_INPUT:
        return "flow_input"
    if input_source == InputSource.ALL_PREVIOUS_STEPS:
        return "fan_in"
    if previous_field_refs:
        return "field_refs"
    if previous_output_refs:
        return "text_anchor"
    return "implicit_previous"


def _planned_step_is_source_reader(step: PlannedStep) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _FILE_INPUT_TYPES | {InputType.TEXT}
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
    )


def _fixed_audio_transcription_step(
    *,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
    name: str | None = None,
    instructions: str | None = None,
    review_mode: FlowStepReviewMode | None = None,
) -> PlannedStep:
    if ui_language == "sv":
        default_name = "Transkribera ljud"
        default_instructions = (
            "Transkribera det uppladdade ljudet till text innan analys "
            "eller artefaktgenerering."
        )
    else:
        default_name = "Transcribe audio"
        default_instructions = (
            "Transcribe the uploaded audio into text before downstream analysis "
            "or artifact generation."
        )
    return PlannedStep(
        role="transcription",
        name=name or default_name,
        instructions=instructions or default_instructions,
        input_source=InputSource.FLOW_INPUT,
        input_type=InputType.AUDIO,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.TRANSCRIBE_ONLY,
        underlag_channel="flow_input",
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        review_mode=review_mode,
    )


def _offset_previous_field_refs(
    refs: Sequence[PreviousFieldRef],
    *,
    compiled_step_offset: int,
) -> tuple[PreviousFieldRef, ...]:
    if compiled_step_offset == 0:
        return tuple(refs)
    return tuple(
        ref.model_copy(update={"from_step": ref.from_step + compiled_step_offset})
        for ref in refs
    )


def _offset_previous_output_refs(
    refs: Sequence[PreviousOutputRef],
    *,
    compiled_step_offset: int,
) -> tuple[PreviousOutputRef, ...]:
    if compiled_step_offset == 0:
        return tuple(refs)
    return tuple(
        ref.model_copy(update={"from_step": ref.from_step + compiled_step_offset})
        for ref in refs
    )


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
    step_drafts = [
        _new_step_draft_from_planned_step(planned_step) for planned_step in plan.steps
    ]
    step_drafts = clear_terminal_schema_output_fields(
        steps=step_drafts,
        terminal_output_schema=plan.terminal_output_schema,
    )
    step_drafts = complete_source_reader_contracts(
        steps=step_drafts,
        terminal_output_schema=plan.terminal_output_schema,
        required_fields=plan.source_reader_required_fields,
    )
    form_fields = list(plan.form_fields)
    step_drafts, form_fields, dropped_source_contract_field_names = (
        drop_source_contract_shadow_form_fields(
            steps=step_drafts,
            form_fields=form_fields,
        )
    )
    log_dropped_source_contract_shadow_fields(
        field_names=dropped_source_contract_field_names
    )
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
        runtime_required=step.runtime_required,
        runtime_max_files=step.runtime_max_files,
        uses_form_fields=list(step.form_field_refs),
        uses_previous_fields=list(step.previous_field_refs),
        uses_previous_outputs=list(step.previous_output_refs),
        output_fields=list(step.output_fields),
        document_delivery_mode=step.document_delivery_mode,
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )
