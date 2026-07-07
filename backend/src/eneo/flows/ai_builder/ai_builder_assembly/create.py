from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

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
    derive_underlag_channel,
    planned_step_is_source_reader,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    SourceCaptureField,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    complete_structured_source_reader_fields,
    log_dropped_source_contract_shadow_fields,
    source_capture_fields_from_terminal_schema,
    source_contract_shadow_form_field_names,
    source_reader_leaf_field_name,
    structured_fields_have_source_leaf,
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

logger = logging.getLogger(__name__)

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

CreateAssemblyRejectionReason = Literal[
    "aggregate_requires_text_or_document_output",
    "all_previous_step_cannot_use_explicit_refs",
    "audio_requires_linear",
    "docx_template_form_fields_mismatch",
    "docx_template_shape_unsupported",
    "empty_steps",
    "explicit_refs_not_supported",
    "invalid_template_fill_mode",
    "plan_invariant_failed",
    "pure_audio_transcription_requires_no_reader_fields",
    "pure_audio_transcription_shape_unsupported",
    "source_file_first_step_requires_json",
    "step_output_type_mismatch",
    "terminal_schema_requires_json_terminal",
    "unsupported_aggregation_intent",
    "unsupported_architecture_hints",
    "unsupported_final_output_type",
    "unsupported_output_mode",
    "unsupported_runtime_input_type",
]

_REJECTION_FEEDBACK: dict[CreateAssemblyRejectionReason, str] = {
    "aggregate_requires_text_or_document_output": (
        "Aggregate and compare create flows must end in text or a document artifact; "
        "remove the JSON terminal shape or make the flow linear."
    ),
    "all_previous_step_cannot_use_explicit_refs": (
        "The fan-in step must combine prior outputs as a whole. Remove explicit "
        "form-field or previous-output refs from that semantic step."
    ),
    "audio_requires_linear": "Audio create flows must be linear.",
    "docx_template_form_fields_mismatch": (
        "DOCX template-fill flows must reference every template field exactly once "
        "in the content-writing semantic step."
    ),
    "docx_template_shape_unsupported": (
        "DOCX template-fill flows require one text-writing semantic step for the "
        "template variables."
    ),
    "empty_steps": "The proposal must contain at least one semantic step.",
    "explicit_refs_not_supported": (
        "Create-mode semantic steps must not author uses_previous_fields or "
        "uses_previous_outputs. Describe the data needed in instructions and "
        "output_fields instead."
    ),
    "invalid_template_fill_mode": (
        "template_fill output mode is only valid for DOCX template-fill flows."
    ),
    "plan_invariant_failed": "The assembled flow violated a construction invariant.",
    "pure_audio_transcription_requires_no_reader_fields": (
        "Pure audio transcription must not request structured source-reader fields."
    ),
    "pure_audio_transcription_shape_unsupported": (
        "Pure audio transcription requires one plain text semantic step and no "
        "runtime form fields."
    ),
    "source_file_first_step_requires_json": (
        "For document and file inputs, the first semantic step must extract JSON "
        "before text-writing steps consume it."
    ),
    "step_output_type_mismatch": (
        "A semantic step's output_type or output_fields conflicts with the confirmed "
        "terminal output shape."
    ),
    "terminal_schema_requires_json_terminal": (
        "A terminal output schema can only be used by a linear JSON terminal flow."
    ),
    "unsupported_aggregation_intent": (
        "Create assembly supports only linear, aggregate, and compare intents."
    ),
    "unsupported_architecture_hints": (
        "The confirmed architecture pattern is not supported by create assembly."
    ),
    "unsupported_final_output_type": (
        "Create assembly supports text, JSON, PDF, and DOCX terminal outputs."
    ),
    "unsupported_output_mode": (
        "Create assembly supports pass-through output mode for semantic model steps."
    ),
    "unsupported_runtime_input_type": (
        "Create assembly supports text, JSON, audio, document, and file inputs."
    ),
}


@dataclass(frozen=True, slots=True)
class CreateAssemblyRejection:
    reason: CreateAssemblyRejectionReason
    step_index: int | None = None
    detail: str | None = None

    @property
    def failure_code(self) -> str:
        return f"assembly_{self.reason}"

    @property
    def feedback(self) -> str:
        feedback = self.detail or _REJECTION_FEEDBACK[self.reason]
        if self.step_index is None:
            return feedback
        return f"Step {self.step_index}: {feedback}"


def _reject(
    reason: CreateAssemblyRejectionReason,
    *,
    step_index: int | None = None,
    detail: str | None = None,
) -> CreateAssemblyRejection:
    return CreateAssemblyRejection(
        reason=reason,
        step_index=step_index,
        detail=detail,
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
) -> FlowDraftSpecCore | CreateAssemblyRejection:
    try:
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
        if isinstance(plan, CreateAssemblyRejection):
            return plan
        return lower_assembly_plan(plan)
    except ValueError as error:
        return _reject("plan_invariant_failed", detail=str(error))


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
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    if not _architecture_hints_are_supported(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    ):
        return _reject("unsupported_architecture_hints")
    if aggregation_intent not in {"linear", "aggregate", "compare"}:
        return _reject("unsupported_aggregation_intent")
    if not intent.steps:
        return _reject("empty_steps")
    if runtime_input_type not in _SOURCE_INPUT_TYPES:
        return _reject("unsupported_runtime_input_type")
    if runtime_input_type == InputType.AUDIO and aggregation_intent != "linear":
        return _reject("audio_requires_linear")
    document_artifact_requested = final_output_type in _DOCUMENT_OUTPUT_TYPES
    if (
        final_output_type
        not in {OutputType.TEXT, OutputType.JSON} | _DOCUMENT_OUTPUT_TYPES
    ):
        return _reject("unsupported_final_output_type")
    template_fill_requested = (
        final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    )
    if final_output_mode == OutputMode.TEMPLATE_FILL and not template_fill_requested:
        return _reject("invalid_template_fill_mode")
    if terminal_output_schema is not None and (
        document_artifact_requested or final_output_type != OutputType.JSON
    ):
        return _reject("terminal_schema_requires_json_terminal")
    if aggregation_intent != "linear" and (
        terminal_output_schema is not None or final_output_type == OutputType.JSON
    ):
        return _reject("aggregate_requires_text_or_document_output")
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
            return _reject("pure_audio_transcription_requires_no_reader_fields")
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
        return _reject("unsupported_output_mode")

    terminal_semantic_output_type = (
        OutputType.TEXT if document_artifact_requested else final_output_type
    )
    form_field_names = {field.name for field in form_fields}
    placed_form_fields: set[str] = set()
    planned_steps: list[PlannedStep] = []
    semantic_steps = _semantic_steps_without_terminal_document_render_helper(
        intent.steps,
        final_output_type=final_output_type,
        document_artifact_requested=document_artifact_requested,
    )
    previous_output_type: OutputType | None = None
    has_source_prefix = False
    if runtime_input_type == InputType.AUDIO:
        transcription_step = fixed_audio_transcription_step(
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
        planned_steps.append(transcription_step)
        previous_output_type = OutputType.TEXT
        has_source_prefix = True
    for index, semantic_step in enumerate(semantic_steps):
        is_terminal_semantic_step = index == len(semantic_steps) - 1
        if semantic_step.uses_previous_fields or semantic_step.uses_previous_outputs:
            return _reject("explicit_refs_not_supported", step_index=index + 1)
        step_output_type = _linear_step_output_type(
            output_type=semantic_step.output_type,
            output_fields=semantic_step.output_fields,
            final_output_type=terminal_semantic_output_type,
            is_terminal=is_terminal_semantic_step,
        )
        if step_output_type is None:
            return _reject("step_output_type_mismatch", step_index=index + 1)
        if (
            index == 0
            and runtime_input_type in _FILE_INPUT_TYPES
            and step_output_type != OutputType.JSON
        ):
            return _reject(
                "source_file_first_step_requires_json",
                step_index=index + 1,
            )
        input_source = _linear_step_input_source(
            step_index=index,
            semantic_step_count=len(semantic_steps),
            aggregation_intent=aggregation_intent,
            has_source_prefix=has_source_prefix,
        )
        if input_source == InputSource.ALL_PREVIOUS_STEPS and (
            semantic_step.uses_form_fields
            or semantic_step.uses_previous_fields
            or semantic_step.uses_previous_outputs
        ):
            return _reject(
                "all_previous_step_cannot_use_explicit_refs",
                step_index=index + 1,
            )
        input_type = _linear_step_input_type(
            input_source=input_source,
            runtime_input_type=runtime_input_type,
            previous_output_type=previous_output_type,
            output_type=step_output_type,
        )
        previous_planned_step = (
            planned_steps[-1] if input_source == InputSource.PREVIOUS_STEP else None
        )
        planned_step = PlannedStep(
            role=_linear_step_role(
                output_type=step_output_type,
                is_terminal=is_terminal_semantic_step,
                document_artifact_requested=document_artifact_requested,
            ),
            name=semantic_step.name,
            instructions=semantic_step.instructions,
            input_source=input_source,
            input_type=input_type,
            output_type=step_output_type,
            output_mode=semantic_output_mode,
            underlag_channel=derive_underlag_channel(
                input_source=input_source,
                input_type=input_type,
                previous_step=previous_planned_step,
                previous_field_refs=(),
                previous_output_refs=(),
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
        return _reject("docx_template_form_fields_mismatch")
    if document_artifact_requested:
        renderer_step = render_verbatim_step(
            output_type=final_output_type,
            ui_language=ui_language,
        )
        planned_steps.append(renderer_step)
    completed_steps = _complete_planned_source_reader_contracts(
        tuple(planned_steps),
        terminal_output_schema=terminal_output_schema,
        required_fields=source_reader_required_fields,
    )
    completed_steps, admitted_form_fields = (
        _drop_planned_source_contract_shadow_form_fields(
            planned_steps=completed_steps,
            form_fields=tuple(form_fields),
        )
    )
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=admitted_form_fields,
        steps=completed_steps,
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=source_reader_required_fields,
        aggregation_intent=aggregation_intent,
        ui_language=ui_language,
    )


def _semantic_steps_without_terminal_document_render_helper(
    steps: Sequence[SemanticStepIntent],
    *,
    final_output_type: OutputType,
    document_artifact_requested: bool,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if (
        not document_artifact_requested
        or final_output_type not in _DOCUMENT_OUTPUT_TYPES
        or len(semantic_steps) < 2
    ):
        return semantic_steps

    previous_step = semantic_steps[-2]
    helper_candidate = semantic_steps[-1]
    previous_output_type = _linear_step_output_type(
        output_type=previous_step.output_type,
        output_fields=previous_step.output_fields,
        final_output_type=OutputType.TEXT,
        is_terminal=False,
    )
    if previous_output_type != OutputType.TEXT:
        return semantic_steps
    helper_output_type = _linear_step_output_type(
        output_type=helper_candidate.output_type,
        output_fields=helper_candidate.output_fields,
        final_output_type=OutputType.TEXT,
        is_terminal=True,
    )
    if helper_output_type != OutputType.TEXT:
        return semantic_steps
    if not _is_plain_terminal_document_helper(
        helper_candidate,
        final_output_type=final_output_type,
    ):
        return semantic_steps

    logger.info(
        "ai_builder_terminal_document_render_helper_dropped",
        extra={
            "step_name": helper_candidate.name,
            "final_output_type": final_output_type.value,
        },
    )
    return semantic_steps[:-1]


def _is_plain_terminal_document_helper(
    step: SemanticStepIntent,
    *,
    final_output_type: OutputType,
) -> bool:
    if (
        step.output_fields
        or step.uses_form_fields
        or step.knowledge_refs
        or step.mcp_server_refs
        or step.mcp_tool_refs
        or step.citations_requested
        or step.review_mode is not None
    ):
        return False
    return _mentions_output_artifact_type(
        f"{step.name} {step.instructions}",
        final_output_type=final_output_type,
    )


def _mentions_output_artifact_type(
    text: str,
    *,
    final_output_type: OutputType,
) -> bool:
    artifact_type = re.escape(final_output_type.value)
    return (
        re.search(rf"(?<![a-z0-9]){artifact_type}(?![a-z0-9])", text.casefold())
        is not None
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
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    if (
        runtime_input_type not in _FILE_INPUT_TYPES
        or aggregation_intent != "linear"
        or len(intent.steps) != 1
    ):
        return _reject("docx_template_shape_unsupported")
    semantic_step = intent.steps[0]
    if (
        semantic_step.output_fields
        or semantic_step.uses_previous_fields
        or semantic_step.uses_previous_outputs
        or semantic_step.output_type not in {None, OutputType.TEXT}
    ):
        return _reject("docx_template_shape_unsupported", step_index=1)
    form_field_names = {field.name for field in form_fields}
    if set(semantic_step.uses_form_fields) != form_field_names:
        return _reject("docx_template_form_fields_mismatch", step_index=1)

    reader_step = template_variable_reader_step(
        runtime_input_type=runtime_input_type,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )
    content_input_type = (
        InputType.TEXT if semantic_step.uses_form_fields else InputType.JSON
    )
    content_step = PlannedStep(
        role="transform",
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=content_input_type,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel=derive_underlag_channel(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=content_input_type,
            previous_step=reader_step,
            previous_field_refs=(),
            previous_output_refs=(),
        ),
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
    completed_steps = _complete_planned_source_reader_contracts(
        planned_steps,
        terminal_output_schema=None,
        required_fields=source_reader_required_fields,
    )
    completed_steps, admitted_form_fields = (
        _drop_planned_source_contract_shadow_form_fields(
            planned_steps=completed_steps,
            form_fields=tuple(form_fields),
        )
    )
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=admitted_form_fields,
        steps=completed_steps,
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
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    if len(intent.steps) != 1 or form_fields:
        return _reject("pure_audio_transcription_shape_unsupported")
    semantic_step = intent.steps[0]
    if (
        semantic_step.output_fields
        or semantic_step.uses_form_fields
        or semantic_step.uses_previous_fields
        or semantic_step.uses_previous_outputs
        or semantic_step.output_type not in {None, OutputType.TEXT}
    ):
        return _reject(
            "pure_audio_transcription_shape_unsupported",
            step_index=1,
        )
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
) -> InputType:
    if input_source == InputSource.FLOW_INPUT:
        return runtime_input_type
    if input_source == InputSource.ALL_PREVIOUS_STEPS:
        return InputType.TEXT
    if previous_output_type == OutputType.JSON:
        if output_type == OutputType.TEXT:
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


def _complete_planned_source_reader_contracts(
    planned_steps: tuple[PlannedStep, ...],
    *,
    terminal_output_schema: JsonObject | None,
    required_fields: tuple[SourceCaptureField, ...],
) -> tuple[PlannedStep, ...]:
    source_reader_indexes = tuple(
        index
        for index, planned_step in enumerate(planned_steps)
        if planned_step_is_source_reader(planned_step)
    )
    if not source_reader_indexes:
        return planned_steps

    fields_by_index: dict[int, list[SourceCaptureField]] = {}
    terminal_fields = (
        source_capture_fields_from_terminal_schema(terminal_output_schema)
        if terminal_output_schema is not None
        else ()
    )
    global_fields = (*required_fields, *terminal_fields)
    missing_global_fields = [
        field
        for field in global_fields
        if not any(
            structured_fields_have_source_leaf(
                planned_steps[index].output_fields,
                field.name,
            )
            for index in source_reader_indexes
        )
    ]
    if missing_global_fields:
        if len(source_reader_indexes) != 1:
            raise ValueError(
                "FlowAssemblyPlan source-reader field completion requires "
                "exactly one source reader when global fields are missing."
            )
        fields_by_index.setdefault(source_reader_indexes[0], []).extend(
            missing_global_fields
        )

    source_reader_index_set = set(source_reader_indexes)
    for planned_step in planned_steps:
        for ref in planned_step.previous_field_refs:
            source_index = ref.from_step - 1
            if source_index not in source_reader_index_set:
                continue
            field_name = source_reader_leaf_field_name(ref.field_path)
            if not field_name or structured_fields_have_source_leaf(
                planned_steps[source_index].output_fields,
                field_name,
            ):
                continue
            fields_by_index.setdefault(source_index, []).append(
                SourceCaptureField(name=field_name, description=ref.label)
            )

    if not fields_by_index:
        return planned_steps

    updated_steps = list(planned_steps)
    for index, fields in fields_by_index.items():
        planned_step = planned_steps[index]
        completed_fields = complete_structured_source_reader_fields(
            planned_step.output_fields,
            required_fields=tuple(fields),
        )
        if completed_fields == planned_step.output_fields:
            continue
        updated_steps[index] = replace(planned_step, output_fields=completed_fields)
        logger.info(
            "ai_builder_source_reader_contract_completed",
            extra={
                "step_index": index + 1,
                "field_names": [field.name for field in fields],
            },
        )
    return tuple(updated_steps)


def _drop_planned_source_contract_shadow_form_fields(
    *,
    planned_steps: tuple[PlannedStep, ...],
    form_fields: tuple[FormFieldSpec, ...],
) -> tuple[tuple[PlannedStep, ...], tuple[FormFieldSpec, ...]]:
    dropped_names = set(
        source_contract_shadow_form_field_names(
            output_fields_by_step=tuple(
                planned_step.output_fields
                for planned_step in planned_steps
                if planned_step_is_source_reader(planned_step)
            ),
            form_fields=form_fields,
        )
    )
    if not dropped_names:
        return planned_steps, form_fields
    log_dropped_source_contract_shadow_fields(field_names=sorted(dropped_names))
    return (
        tuple(
            _without_planned_form_field_refs(
                planned_step,
                dropped_names=dropped_names,
            )
            for planned_step in planned_steps
        ),
        tuple(field for field in form_fields if field.name not in dropped_names),
    )


def _without_planned_form_field_refs(
    planned_step: PlannedStep,
    *,
    dropped_names: set[str],
) -> PlannedStep:
    if not planned_step.form_field_refs:
        return planned_step
    form_field_refs = tuple(
        field_name
        for field_name in planned_step.form_field_refs
        if field_name not in dropped_names
    )
    if form_field_refs == planned_step.form_field_refs:
        return planned_step
    return replace(planned_step, form_field_refs=form_field_refs)
