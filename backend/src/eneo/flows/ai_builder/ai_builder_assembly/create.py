from __future__ import annotations

from collections.abc import Sequence

from eneo.flows.ai_builder.ai_builder_assembly.fixed_steps import (
    fixed_audio_transcription_step,
    render_verbatim_step,
    template_fill_step,
    template_variable_reader_step,
)
from eneo.flows.ai_builder.ai_builder_assembly.lower import lower_assembly_plan
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    FlowAssemblyPlan,
    PlannedStep,
    PlannedStepRole,
    UnderlagChannel,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    SourceCaptureField,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    FLOW_INPUT_DOCUMENT_UPLOAD,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
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
_DOCX_TEMPLATE_PATTERN_ID = "document_to_docx_template"
_DOCX_TEMPLATE_PATTERN_CHAIN_STEPS = frozenset(
    {
        FLOW_INPUT_DOCUMENT_UPLOAD,
        EXTRACT_TEMPLATE_VARIABLES_STEP,
        TEMPLATE_FILL_DOCX_STEP,
    }
)
_SUPPORTED_STRUCTURAL_PATTERN_IDS = frozenset(
    {
        "comparison",
        "document_to_pdf_report",
        "document_to_structured_report",
        "extract_structured_fields",
        "form_field_runtime_inputs",
        "json_to_artifact_report",
        "json_to_structured_payload",
        "json_to_text_summary",
        "mcp_tool_step",
        "summarize_text",
        "text_to_artifact_report",
    }
)


def try_compile_create_intent_with_assembly(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    form_fields: Sequence[FormFieldSpec],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: AggregationIntent,
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
    return lower_assembly_plan(plan)


def _assemble_create_intent(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    form_fields: Sequence[FormFieldSpec],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: AggregationIntent,
    terminal_output_schema: JsonObject | None,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> FlowAssemblyPlan | None:
    if (
        not _architecture_hints_are_supported(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
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
    template_fill_requested = (
        final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    )
    if final_output_mode == OutputMode.TEMPLATE_FILL and not template_fill_requested:
        return None
    if terminal_output_schema is not None and (
        document_artifact_requested or final_output_type != OutputType.JSON
    ):
        return None
    if aggregation_intent != "linear" and (
        terminal_output_schema is not None or final_output_type == OutputType.JSON
    ):
        return None
    if template_fill_requested:
        return _assemble_docx_template_fill(
            intent,
            runtime_input_type=runtime_input_type,
            form_fields=form_fields,
            source_reader_required_fields=source_reader_required_fields,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            aggregation_intent=aggregation_intent,
            ui_language=ui_language,
        )
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
        transcription_step = fixed_audio_transcription_step(
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
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
        planned_steps.append(planned_step)
        placed_form_fields.update(planned_step.form_field_refs)
        previous_output_type = step_output_type

    if placed_form_fields != form_field_names:
        return None
    if document_artifact_requested:
        renderer_step = render_verbatim_step(
            output_type=final_output_type,
            ui_language=ui_language,
        )
        planned_steps.append(renderer_step)
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=tuple(form_fields),
        steps=tuple(planned_steps),
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=source_reader_required_fields,
        aggregation_intent=aggregation_intent,
        ui_language=ui_language,
    )


def _architecture_hints_are_supported(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    if not pattern_ids and not chain_steps:
        return True
    if not chain_steps and set(pattern_ids) <= _SUPPORTED_STRUCTURAL_PATTERN_IDS:
        return True
    if runtime_input_type == InputType.AUDIO:
        return set(pattern_ids) <= _AUDIO_PATTERN_IDS and set(chain_steps) <= set(
            _AUDIO_PATTERN_CHAIN_STEPS
        )
    if (
        runtime_input_type in _FILE_INPUT_TYPES
        and final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    ):
        return set(pattern_ids) <= {_DOCX_TEMPLATE_PATTERN_ID} and set(
            chain_steps
        ) <= set(_DOCX_TEMPLATE_PATTERN_CHAIN_STEPS)
    return False


def _assemble_docx_template_fill(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    form_fields: Sequence[FormFieldSpec],
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    runtime_required: bool,
    runtime_max_files: int | None,
    aggregation_intent: AggregationIntent,
    ui_language: str | None,
) -> FlowAssemblyPlan | None:
    if (
        runtime_input_type not in _FILE_INPUT_TYPES
        or aggregation_intent != "linear"
        or len(intent.steps) != 1
    ):
        return None
    semantic_step = intent.steps[0]
    if (
        not _previous_refs_are_immediate(semantic_step, step_index=0)
        or semantic_step.output_fields
        or semantic_step.uses_previous_fields
        or semantic_step.uses_previous_outputs
        or semantic_step.output_type not in {None, OutputType.TEXT}
    ):
        return None
    form_field_names = {field.name for field in form_fields}
    if set(semantic_step.uses_form_fields) != form_field_names:
        return None

    reader_step = template_variable_reader_step(
        runtime_input_type=runtime_input_type,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )
    content_step = PlannedStep(
        role="transform",
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT if semantic_step.uses_form_fields else InputType.JSON,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel="implicit_previous",
        form_field_refs=tuple(semantic_step.uses_form_fields),
        model_ref=semantic_step.model_ref,
        knowledge_refs=tuple(semantic_step.knowledge_refs),
        mcp_server_refs=tuple(semantic_step.mcp_server_refs),
        mcp_tool_refs=tuple(semantic_step.mcp_tool_refs),
        citations_requested=semantic_step.citations_requested,
        review_mode=semantic_step.review_mode,
    )
    fixed_template_fill_step = template_fill_step(ui_language=ui_language)
    planned_steps = (reader_step, content_step, fixed_template_fill_step)
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=tuple(form_fields),
        steps=planned_steps,
        terminal_output_schema=None,
        source_reader_required_fields=source_reader_required_fields,
        aggregation_intent="linear",
        ui_language=ui_language,
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
    planned_step = fixed_audio_transcription_step(
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
        review_mode=semantic_step.review_mode,
    )
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=(),
        steps=(planned_step,),
        terminal_output_schema=None,
        source_reader_required_fields=(),
        aggregation_intent="linear",
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
