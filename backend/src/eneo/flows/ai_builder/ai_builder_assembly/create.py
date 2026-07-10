from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, NoReturn

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
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
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    add_runtime_source_file_id_field,
    complete_structured_source_reader_fields,
    log_dropped_source_contract_shadow_fields,
    source_capture_fields_from_terminal_schema,
    source_contract_shadow_form_field_names,
    source_reader_leaf_field_name,
    structured_fields_have_document_items,
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
_FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID = "form_field_runtime_inputs"
_AUDIO_PATTERN_IDS = frozenset(
    {_AUDIO_TRANSCRIPTION_PATTERN_ID, _AUDIO_ARTIFACT_PATTERN_ID}
)
_AUDIO_PATTERN_IDS_WITH_FORM_FIELDS = _AUDIO_PATTERN_IDS | frozenset(
    {_FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID}
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
    "document_report_compose_topology_missing",
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
    "document_report_compose_topology_missing": (
        "Document report flows with source sections must end with a deterministic "
        "compose_text body writer before the renderer."
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
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    report_disposition: str | None,
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
            result_contract_output_fields=result_contract_output_fields,
            report_disposition=report_disposition,
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
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    report_disposition: str | None,
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
        ui_language=ui_language,
    )
    semantic_steps = _semantic_steps_with_single_source_report_reader(
        semantic_steps,
        runtime_input_type=runtime_input_type,
        final_semantic_output_type=terminal_semantic_output_type,
        source_reader_required_fields=source_reader_required_fields,
        ui_language=ui_language,
    )
    semantic_steps = _semantic_steps_with_terminal_text_fields_folded(
        semantic_steps,
        final_semantic_output_type=terminal_semantic_output_type,
        ui_language=ui_language,
    )
    semantic_steps = _semantic_steps_with_result_contract_fields(
        semantic_steps,
        runtime_input_type=runtime_input_type,
        final_semantic_output_type=terminal_semantic_output_type,
        result_contract_output_fields=result_contract_output_fields,
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
        aggregate_terminal_previous_refs = _aggregate_terminal_previous_structured_refs(
            planned_steps=tuple(planned_steps),
            aggregation_intent=aggregation_intent,
            is_terminal_semantic_step=is_terminal_semantic_step,
        )
        input_source = _linear_step_input_source(
            step_index=index,
            semantic_step_count=len(semantic_steps),
            aggregation_intent=aggregation_intent,
            has_source_prefix=has_source_prefix,
            prior_step_count=len(planned_steps),
            aggregate_terminal_uses_source_refs=bool(aggregate_terminal_previous_refs),
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
        previous_field_refs = (
            aggregate_terminal_previous_refs
            or _derived_terminal_text_previous_field_refs(
                planned_steps=tuple(planned_steps),
                input_source=input_source,
                input_type=input_type,
                output_type=step_output_type,
                is_terminal_semantic_step=is_terminal_semantic_step,
            )
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
                previous_field_refs=previous_field_refs,
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
    completed_steps = _apply_per_source_reader_execution(
        completed_steps,
        ui_language=ui_language,
    )
    completed_steps = _ensure_document_report_section_writer(
        completed_steps,
        report_disposition=report_disposition,
        final_output_type=final_output_type,
        ui_language=ui_language,
    )
    completed_steps = _apply_previous_document_item_map_execution(
        completed_steps,
        ui_language=ui_language,
    )
    completed_steps = _ensure_document_report_overview_writer(
        completed_steps,
        report_disposition=report_disposition,
        final_output_type=final_output_type,
        ui_language=ui_language,
    )
    completed_steps = _replace_document_report_body_writer_with_compose(
        completed_steps,
        report_disposition=report_disposition,
        final_output_type=final_output_type,
        ui_language=ui_language,
    )
    if _document_report_compose_required(
        completed_steps,
        report_disposition=report_disposition,
        final_output_type=final_output_type,
    ) and not _has_terminal_compose_renderer_topology(completed_steps):
        _raise_document_report_compose_topology_missing(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
            semantic_step_count=len(semantic_steps),
        )
    completed_steps = _annotate_report_disposition(
        completed_steps,
        report_disposition=report_disposition,
        ui_language=ui_language,
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
    ui_language: str | None,
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
    if helper_candidate.output_type not in {None, OutputType.TEXT, final_output_type}:
        return semantic_steps
    if not _is_plain_terminal_document_helper(
        helper_candidate,
        final_output_type=final_output_type,
    ):
        return semantic_steps

    retained_steps = semantic_steps[:-1]
    if helper_candidate.output_fields:
        retained_steps = (
            *semantic_steps[:-2],
            previous_step.model_copy(
                update={
                    "instructions": _append_terminal_helper_output_fields(
                        previous_step.instructions,
                        helper_candidate.output_fields,
                        ui_language=ui_language,
                    )
                }
            ),
        )

    logger.info(
        "ai_builder_terminal_document_render_helper_dropped",
        extra={
            "step_name": helper_candidate.name,
            "final_output_type": final_output_type.value,
        },
    )
    return retained_steps


def _semantic_steps_with_single_source_report_reader(
    steps: Sequence[SemanticStepIntent],
    *,
    runtime_input_type: InputType,
    final_semantic_output_type: OutputType,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if (
        len(semantic_steps) != 1
        or runtime_input_type not in _FILE_INPUT_TYPES
        or final_semantic_output_type != OutputType.TEXT
    ):
        return semantic_steps

    semantic_step = semantic_steps[0]
    source_fields = tuple(semantic_step.output_fields or ())
    if not source_fields:
        source_fields = _structured_fields_from_source_capture_fields(
            source_reader_required_fields
        )
    if not source_fields:
        return semantic_steps
    source_fields = complete_structured_source_reader_fields(
        source_fields,
        required_fields=(),
    )

    reader_step = semantic_step.model_copy(
        update={
            "name": _source_report_reader_name(ui_language),
            "instructions": _source_report_reader_instructions(ui_language),
            "output_type": OutputType.JSON,
            "output_fields": list(source_fields),
            "uses_form_fields": [],
        }
    )
    writer_step = semantic_step.model_copy(
        update={
            "name": _source_report_writer_name(ui_language),
            "instructions": _append_terminal_helper_output_fields(
                semantic_step.instructions,
                source_fields,
                ui_language=ui_language,
            ),
            "output_type": OutputType.TEXT,
            "output_fields": None,
        }
    )
    return (reader_step, writer_step)


def _semantic_steps_with_terminal_text_fields_folded(
    steps: Sequence[SemanticStepIntent],
    *,
    final_semantic_output_type: OutputType,
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if not semantic_steps or final_semantic_output_type != OutputType.TEXT:
        return semantic_steps

    terminal_step = semantic_steps[-1]
    if not terminal_step.output_fields or terminal_step.output_type not in {
        None,
        OutputType.TEXT,
        OutputType.JSON,
    }:
        return semantic_steps

    folded_terminal_step = terminal_step.model_copy(
        update={
            "instructions": _append_terminal_helper_output_fields(
                terminal_step.instructions,
                terminal_step.output_fields,
                ui_language=ui_language,
            ),
            "output_type": OutputType.TEXT,
            "output_fields": None,
        }
    )
    return (*semantic_steps[:-1], folded_terminal_step)


def _semantic_steps_with_result_contract_fields(
    steps: Sequence[SemanticStepIntent],
    *,
    runtime_input_type: InputType,
    final_semantic_output_type: OutputType,
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if (
        not result_contract_output_fields
        or len(semantic_steps) < 2
        or final_semantic_output_type != OutputType.TEXT
    ):
        return semantic_steps

    terminal_step = semantic_steps[-1]
    terminal_output_type = _linear_step_output_type(
        output_type=terminal_step.output_type,
        output_fields=terminal_step.output_fields,
        final_output_type=final_semantic_output_type,
        is_terminal=True,
    )
    if terminal_output_type != OutputType.TEXT:
        return semantic_steps

    for index in range(len(semantic_steps) - 2, -1, -1):
        if index == 0 and runtime_input_type in _FILE_INPUT_TYPES:
            continue
        candidate = semantic_steps[index]
        candidate_output_type = _linear_step_output_type(
            output_type=candidate.output_type,
            output_fields=candidate.output_fields,
            final_output_type=final_semantic_output_type,
            is_terminal=False,
        )
        if candidate_output_type != OutputType.JSON:
            continue
        completed_fields = _complete_result_contract_output_fields(
            tuple(candidate.output_fields or ()),
            required_fields=result_contract_output_fields,
        )
        if completed_fields == tuple(candidate.output_fields or ()):
            return semantic_steps
        updated_steps = list(semantic_steps)
        updated_steps[index] = candidate.model_copy(
            update={
                "output_type": OutputType.JSON,
                "output_fields": list(completed_fields),
            }
        )
        return tuple(updated_steps)

    return semantic_steps


def _complete_result_contract_output_fields(
    fields: tuple[StructuredFieldDraft, ...],
    *,
    required_fields: tuple[StructuredFieldDraft, ...],
) -> tuple[StructuredFieldDraft, ...]:
    completed_fields = list(fields)
    for required_field in required_fields:
        if _structured_fields_have_leaf(
            tuple(completed_fields),
            required_field.name,
        ):
            continue
        completed_fields.append(required_field)
    return tuple(completed_fields)


def _structured_fields_have_leaf(
    fields: tuple[StructuredFieldDraft, ...],
    field_name: str,
) -> bool:
    for field in fields:
        if field.name == field_name:
            return True
        if field.fields and _structured_fields_have_leaf(
            tuple(field.fields),
            field_name,
        ):
            return True
        if field.item_fields and _structured_fields_have_leaf(
            tuple(field.item_fields),
            field_name,
        ):
            return True
    return False


def _is_plain_terminal_document_helper(
    step: SemanticStepIntent,
    *,
    final_output_type: OutputType,
) -> bool:
    if (
        step.uses_form_fields
        or step.knowledge_refs
        or step.mcp_server_refs
        or step.mcp_tool_refs
        or step.citations_requested
        or step.review_mode is not None
    ):
        return False
    if step.output_type == final_output_type:
        return True
    return _mentions_output_artifact_type(
        f"{step.name} {step.instructions}",
        final_output_type=final_output_type,
    )


def _append_terminal_helper_output_fields(
    instructions: str,
    output_fields: Sequence[StructuredFieldDraft],
    *,
    ui_language: str | None,
) -> str:
    field_names = ", ".join(field.name for field in output_fields if field.name)
    if not field_names:
        return instructions
    if ui_language == "en":
        field_instruction = "Ensure the report body covers these fields: "
    else:
        field_instruction = "Säkerställ att rapporttexten täcker dessa fält: "
    return f"{instructions}\n\n{field_instruction}{field_names}."


def _structured_fields_from_source_capture_fields(
    fields: tuple[SourceCaptureField, ...],
) -> tuple[StructuredFieldDraft, ...]:
    return tuple(
        StructuredFieldDraft(
            name=field.name,
            field_type="string",
            description=field.description or f"Source-derived value for {field.name}.",
        )
        for field in fields
    )


def _source_report_reader_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Extract source fields"
    return "Extrahera källfält"


def _source_report_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Write report"
    return "Skriv rapport"


def _source_report_reader_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Extract the source-derived fields needed before writing the report."
    return "Extrahera de källbaserade fält som behövs innan rapporten skrivs."


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
        pattern_id_set = set(pattern_ids)
        if (
            _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID in pattern_id_set
            and _AUDIO_ARTIFACT_PATTERN_ID not in pattern_id_set
        ):
            return False
        return pattern_id_set <= _AUDIO_PATTERN_IDS_WITH_FORM_FIELDS and set(
            chain_steps
        ) <= set(_AUDIO_PATTERN_CHAIN_STEPS)
    if (
        runtime_input_type in _FILE_INPUT_TYPES
        and final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    ):
        pattern_id_set = set(pattern_ids)
        if (
            _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID in pattern_id_set
            and _DOCX_TEMPLATE_PATTERN_ID not in pattern_id_set
        ):
            return False
        return pattern_id_set <= {
            _DOCX_TEMPLATE_PATTERN_ID,
            _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID,
        } and set(chain_steps) <= set(_DOCX_TEMPLATE_PATTERN_CHAIN_STEPS)
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
    completed_steps = _apply_per_source_reader_execution(
        completed_steps,
        ui_language=ui_language,
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


def _derived_terminal_text_previous_field_refs(
    *,
    planned_steps: tuple[PlannedStep, ...],
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
    is_terminal_semantic_step: bool,
) -> tuple[PreviousFieldRef, ...]:
    if (
        not is_terminal_semantic_step
        or input_source != InputSource.PREVIOUS_STEP
        or input_type != InputType.TEXT
        or output_type != OutputType.TEXT
    ):
        return ()
    json_steps = tuple(
        (index, step)
        for index, step in enumerate(planned_steps, start=1)
        if step.output_type == OutputType.JSON and step.output_fields
    )
    if len(json_steps) < 2:
        return ()
    return tuple(
        PreviousFieldRef(from_step=from_step, field_path=field.name)
        for from_step, step in json_steps
        for field in step.output_fields
    )


def _aggregate_terminal_previous_structured_refs(
    *,
    planned_steps: tuple[PlannedStep, ...],
    aggregation_intent: AggregationIntent,
    is_terminal_semantic_step: bool,
) -> tuple[PreviousFieldRef, ...]:
    if (
        aggregation_intent not in {"aggregate", "compare"}
        or not is_terminal_semantic_step
        or len(planned_steps) < 2
    ):
        return ()
    if any(
        step.output_type != OutputType.JSON or not step.output_fields
        for step in planned_steps
    ):
        return ()
    return tuple(
        PreviousFieldRef(from_step=index, field_path=field.name)
        for index, step in enumerate(planned_steps, start=1)
        for field in step.output_fields
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
    prior_step_count: int,
    aggregate_terminal_uses_source_refs: bool,
) -> InputSource:
    if step_index == 0 and not has_source_prefix:
        return InputSource.FLOW_INPUT
    if (
        aggregation_intent in {"aggregate", "compare"}
        and step_index == semantic_step_count - 1
        and prior_step_count > 1
    ):
        if aggregate_terminal_uses_source_refs:
            return InputSource.PREVIOUS_STEP
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

    updated_steps = list(planned_steps)
    for index in source_reader_indexes:
        fields = fields_by_index.get(index, [])
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


def _apply_per_source_reader_execution(
    planned_steps: tuple[PlannedStep, ...],
    *,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    updated_steps: list[PlannedStep] = []
    changed = False
    for planned_step in planned_steps:
        if not (
            planned_step_is_source_reader(planned_step)
            and structured_fields_have_document_items(planned_step.output_fields)
            and planned_step.input_type in _FILE_INPUT_TYPES
            and planned_step.runtime_max_files != 1
        ):
            updated_steps.append(planned_step)
            continue
        annotated_step = replace(
            planned_step,
            instructions=_append_per_source_reader_instruction(
                planned_step.instructions,
                ui_language=ui_language,
            ),
            output_fields=add_runtime_source_file_id_field(planned_step.output_fields),
            runtime_input_execution_mode="per_source",
        )
        updated_steps.append(annotated_step)
        changed = changed or annotated_step != planned_step
    if not changed:
        return planned_steps
    return tuple(updated_steps)


def _append_per_source_reader_instruction(
    instructions: str,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            "This document reader runs once per uploaded source. Extract facts "
            "only from the current source document and return documents with one "
            "document object."
        )
    else:
        addition = (
            "Den här dokumentläsaren körs en gång per uppladdad källa. Extrahera "
            "bara fakta från det aktuella källdokumentet och returnera documents "
            "med ett dokumentobjekt."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _ensure_document_report_section_writer(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: str | None,
    final_output_type: OutputType,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    if (
        final_output_type not in _DOCUMENT_OUTPUT_TYPES
        or report_disposition not in {"both", "per_source_sections"}
        or len(planned_steps) < 3
        or _source_section_single_array_index(planned_steps) is not None
    ):
        return planned_steps

    reader_index = _per_source_document_reader_index(planned_steps)
    if reader_index is None:
        return planned_steps
    reader_step = planned_steps[reader_index]
    section_step = PlannedStep(
        role="transform",
        name=_document_report_section_writer_name(ui_language),
        instructions=_document_report_section_writer_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel=derive_underlag_channel(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            previous_step=reader_step,
            previous_field_refs=(),
        ),
        output_fields=(_document_report_section_array_field(ui_language),),
    )
    logger.info(
        "ai_builder_document_report_section_writer_inserted",
        extra={"reader_step_name": reader_step.name},
    )
    replaced_index = reader_index + 1
    if replaced_index < len(planned_steps) and _step_outputs_weak_section_text(
        planned_steps[replaced_index]
    ):
        logger.info(
            "ai_builder_document_report_weak_section_writer_replaced",
            extra={"replaced_step_name": planned_steps[replaced_index].name},
        )
        return (
            *planned_steps[: reader_index + 1],
            section_step,
            *planned_steps[replaced_index + 1 :],
        )
    return (
        *planned_steps[: reader_index + 1],
        section_step,
        *planned_steps[reader_index + 1 :],
    )


def _per_source_document_reader_index(
    planned_steps: tuple[PlannedStep, ...],
) -> int | None:
    for index, planned_step in enumerate(planned_steps):
        if (
            planned_step_is_source_reader(planned_step)
            and planned_step.runtime_input_execution_mode == "per_source"
            and structured_fields_have_document_items(planned_step.output_fields)
        ):
            return index
    return None


def _source_section_single_array_index(
    planned_steps: tuple[PlannedStep, ...],
) -> int | None:
    for index, planned_step in enumerate(planned_steps):
        if _step_outputs_source_section_array(planned_step):
            return index
    return None


def _step_outputs_source_section_array(planned_step: PlannedStep) -> bool:
    if len(planned_step.output_fields) != 1:
        return False
    field = planned_step.output_fields[0]
    if field.field_type != "array":
        return False
    item_field_names = {item.name for item in field.item_fields or ()}
    return {"section_title", "section_body"}.issubset(item_field_names)


def _step_outputs_weak_section_text(planned_step: PlannedStep) -> bool:
    if (
        planned_step.input_source != InputSource.PREVIOUS_STEP
        or planned_step.input_type != InputType.JSON
        or planned_step.output_type != OutputType.JSON
        or len(planned_step.output_fields) != 1
    ):
        return False
    field = planned_step.output_fields[0]
    if field.field_type == "string":
        return _is_section_text_field_name(field.name)
    if field.field_type != "array":
        return False
    return any(
        item.field_type == "string" and _is_section_text_field_name(item.name)
        for item in field.item_fields or ()
    )


def _is_section_text_field_name(name: str) -> bool:
    return name in {"section_text", "section_body"}


def _document_report_section_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Build source sections"
    return "Bygg källavsnitt"


def _document_report_section_writer_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return (
            "Write one finished report section for the current document item. "
            "Use the document title or topic as section_title, not the uploaded "
            "filename. Put the full source-specific prose in section_body."
        )
    return (
        "Skriv ett färdigt rapportavsnitt för den aktuella dokumentposten. "
        "Använd dokumentets titel eller ämne som section_title, inte det "
        "uppladdade filnamnet. Lägg hela den källspecifika rapporttexten i "
        "section_body."
    )


def _document_report_section_array_field(
    ui_language: str | None,
) -> StructuredFieldDraft:
    description = (
        "One finished report section per source document."
        if ui_language == "en"
        else "Ett färdigt rapportavsnitt per källdokument."
    )
    return StructuredFieldDraft(
        name="source_sections",
        field_type="array",
        description=description,
        item_fields=[
            _section_title_field(ui_language),
            _section_body_field(ui_language),
        ],
    )


def _apply_previous_document_item_map_execution(
    planned_steps: tuple[PlannedStep, ...],
    *,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    updated_steps: list[PlannedStep] = []
    changed = False
    for planned_step in planned_steps:
        previous_step = updated_steps[-1] if updated_steps else None
        output_array = _single_output_array_field_name(planned_step.output_fields)
        if (
            previous_step is None
            or not planned_step_is_source_reader(previous_step)
            or previous_step.runtime_input_execution_mode != "per_source"
            or planned_step.input_source != InputSource.PREVIOUS_STEP
            or planned_step.input_type != InputType.JSON
            or planned_step.output_type != OutputType.JSON
            or output_array is None
        ):
            updated_steps.append(planned_step)
            continue
        annotated_step = replace(
            planned_step,
            instructions=_append_previous_document_item_map_instruction(
                planned_step.instructions,
                output_array=output_array,
                ui_language=ui_language,
            ),
            previous_item_map_enabled=True,
        )
        updated_steps.append(annotated_step)
        changed = changed or annotated_step != planned_step
    return tuple(updated_steps) if changed else planned_steps


def _single_output_array_field_name(
    output_fields: tuple[StructuredFieldDraft, ...],
) -> str | None:
    if len(output_fields) != 1:
        return None
    field = output_fields[0]
    if field.field_type != "array":
        return None
    return field.name


def _append_previous_document_item_map_instruction(
    instructions: str,
    *,
    output_array: str,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            "This step runs once per documents[] item from the previous reader. "
            f"Use only the current document item and return {output_array} with "
            "one item."
        )
    else:
        addition = (
            "Det här steget körs en gång per documents[]-post från föregående "
            f"läsare. Använd bara den aktuella dokumentposten och returnera "
            f"{output_array} med en post."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _ensure_document_report_overview_writer(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: str | None,
    final_output_type: OutputType,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    if (
        final_output_type not in _DOCUMENT_OUTPUT_TYPES
        or report_disposition != "both"
        or len(planned_steps) < 4
        or planned_steps[-1].role != "renderer"
        or planned_steps[-2].role != "body_writer"
    ):
        return planned_steps

    body_writer_index = len(planned_steps) - 2
    section_index = _source_section_item_map_index(planned_steps[:body_writer_index])
    if section_index is None:
        return planned_steps
    if (
        _overview_writer_index(
            planned_steps=planned_steps,
            after_index=section_index,
            before_index=body_writer_index,
        )
        is not None
    ):
        return planned_steps

    section_step = planned_steps[section_index]
    overview_step = PlannedStep(
        role="transform",
        name=_document_report_overview_writer_name(ui_language),
        instructions=_document_report_overview_writer_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel=derive_underlag_channel(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            previous_step=section_step,
            previous_field_refs=(),
        ),
        output_fields=_report_overview_fields(ui_language),
    )
    logger.info(
        "ai_builder_document_report_overview_writer_inserted",
        extra={"section_step_name": section_step.name},
    )
    return (
        *planned_steps[: section_index + 1],
        overview_step,
        *planned_steps[section_index + 1 :],
    )


def _document_report_overview_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Write overview"
    return "Skriv översikt"


def _document_report_overview_writer_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return (
            "Write a concise report title and synthesized overview across the "
            "completed source sections. Use only the supplied section content."
        )
    return (
        "Skriv en koncis rapporttitel och samlad översikt över de färdiga "
        "källavsnitten. Använd endast det tillhandahållna avsnittsinnehållet."
    )


def _replace_document_report_body_writer_with_compose(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: str | None,
    final_output_type: OutputType,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    if (
        final_output_type not in _DOCUMENT_OUTPUT_TYPES
        or report_disposition not in {"both", "per_source_sections"}
        or len(planned_steps) < 4
        or planned_steps[-1].role != "renderer"
        or planned_steps[-2].role != "body_writer"
    ):
        return planned_steps

    renderer_step = planned_steps[-1]
    body_writer_step = planned_steps[-2]
    body_writer_index = len(planned_steps) - 2
    section_index = _source_section_item_map_index(planned_steps[:body_writer_index])
    if section_index is None:
        return planned_steps
    overview_index = (
        _overview_writer_index(
            planned_steps=planned_steps,
            after_index=section_index,
            before_index=body_writer_index,
        )
        if report_disposition == "both"
        else None
    )
    if report_disposition == "both" and overview_index is None:
        return planned_steps

    updated_steps = list(planned_steps[:body_writer_index])
    updated_steps[section_index] = _complete_source_section_fields_for_compose(
        updated_steps[section_index],
        ui_language=ui_language,
    )
    if overview_index is not None:
        updated_steps[overview_index] = replace(
            updated_steps[overview_index],
            output_fields=_report_overview_fields(ui_language),
        )

    compose_step = PlannedStep(
        role="body_writer",
        name=body_writer_step.name,
        instructions=_compose_step_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.COMPOSE_TEXT,
        underlag_channel="whole_object",
    )
    return (*updated_steps, compose_step, renderer_step)


def _document_report_compose_required(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: str | None,
    final_output_type: OutputType,
) -> bool:
    return (
        final_output_type in _DOCUMENT_OUTPUT_TYPES
        and report_disposition in {"both", "per_source_sections"}
        and len(planned_steps) >= 2
        and planned_steps[-1].role == "renderer"
    )


def _has_terminal_compose_renderer_topology(
    planned_steps: tuple[PlannedStep, ...],
) -> bool:
    return (
        len(planned_steps) >= 2
        and planned_steps[-2].role == "body_writer"
        and planned_steps[-2].output_mode == OutputMode.COMPOSE_TEXT
        and planned_steps[-1].role == "renderer"
    )


def _raise_document_report_compose_topology_missing(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    semantic_step_count: int,
) -> NoReturn:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=_REJECTION_FEEDBACK["document_report_compose_topology_missing"],
        log_context={
            "failure_code": "assembly_document_report_compose_topology_missing",
            "reason": "document_report_compose_topology_missing",
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
            "final_output_mode": (
                final_output_mode.value if final_output_mode is not None else None
            ),
            "pattern_ids": ",".join(pattern_ids),
            "chain_steps": ",".join(chain_steps),
            "semantic_step_count": semantic_step_count,
        },
    )


def _source_section_item_map_index(
    planned_steps: tuple[PlannedStep, ...],
) -> int | None:
    for index in range(len(planned_steps) - 1, -1, -1):
        planned_step = planned_steps[index]
        if (
            planned_step.previous_item_map_enabled
            and _single_output_array_field_name(planned_step.output_fields) is not None
        ):
            return index
    return None


def _overview_writer_index(
    *,
    planned_steps: tuple[PlannedStep, ...],
    after_index: int,
    before_index: int,
) -> int | None:
    for index in range(before_index - 1, after_index, -1):
        planned_step = planned_steps[index]
        if (
            planned_step.output_type == OutputType.JSON
            and not planned_step.previous_item_map_enabled
            and planned_step.output_fields
        ):
            return index
    return None


def _complete_source_section_fields_for_compose(
    planned_step: PlannedStep,
    *,
    ui_language: str | None,
) -> PlannedStep:
    if len(planned_step.output_fields) != 1:
        return planned_step
    array_field = planned_step.output_fields[0]
    if array_field.field_type != "array":
        return planned_step
    item_fields = list(array_field.item_fields or ())
    item_fields = _ensure_structured_field(
        item_fields,
        _section_title_field(ui_language),
    )
    item_fields = _ensure_structured_field(
        item_fields,
        _section_body_field(ui_language),
    )
    item_fields = _ensure_structured_field(
        item_fields,
        _runtime_source_label_field(ui_language),
    )
    item_fields = _ensure_structured_field(
        item_fields,
        _runtime_source_file_id_field(ui_language),
    )
    completed_array_field = array_field.model_copy(update={"item_fields": item_fields})
    return replace(planned_step, output_fields=(completed_array_field,))


def _ensure_structured_field(
    fields: list[StructuredFieldDraft],
    field: StructuredFieldDraft,
) -> list[StructuredFieldDraft]:
    if any(existing.name == field.name for existing in fields):
        return fields
    return [*fields, field]


def _section_title_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Human-readable section heading from the document title or topic, not the uploaded filename."
        if ui_language == "en"
        else "Mänsklig avsnittsrubrik från dokumentets titel eller ämne, inte uppladdat filnamn."
    )
    return StructuredFieldDraft(
        name="section_title",
        field_type="string",
        description=description,
    )


def _section_body_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Finished source-specific report section body."
        if ui_language == "en"
        else "Färdig källspecifik rapporttext för avsnittet."
    )
    return StructuredFieldDraft(
        name="section_body",
        field_type="string",
        description=description,
    )


def _runtime_source_label_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Runtime-owned uploaded source label. The runtime fills this field."
        if ui_language == "en"
        else "Runtimeägd källetikett för uppladdad fil. Runtime fyller fältet."
    )
    return StructuredFieldDraft(
        name="source_label",
        field_type="string",
        description=description,
    )


def _runtime_source_file_id_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Runtime-owned uploaded source file id. The runtime fills this field."
        if ui_language == "en"
        else "Runtimeägt fil-id för uppladdad källa. Runtime fyller fältet."
    )
    return StructuredFieldDraft(
        name="source_file_id",
        field_type="string",
        description=description,
    )


def _report_overview_fields(
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    if ui_language == "en":
        return (
            StructuredFieldDraft(
                name="report_title",
                field_type="string",
                description="Final report title.",
            ),
            StructuredFieldDraft(
                name="overall_overview",
                field_type="string",
                description="Synthesized overview or conclusion across all sources.",
            ),
        )
    return (
        StructuredFieldDraft(
            name="report_title",
            field_type="string",
            description="Slutrapportens titel.",
        ),
        StructuredFieldDraft(
            name="overall_overview",
            field_type="string",
            description="Samlad översikt eller slutsats över alla källor.",
        ),
    )


def _compose_step_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Assemble the final report deterministically from completed sections."
    return "Sätt ihop slutrapporten deterministiskt från färdiga avsnitt."


def _annotate_report_disposition(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: str | None,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    if report_disposition is None:
        return planned_steps
    updated_steps: list[PlannedStep] = []
    changed = False
    for planned_step in planned_steps:
        if (
            planned_step.role != "body_writer"
            or planned_step.output_mode == OutputMode.COMPOSE_TEXT
        ):
            updated_steps.append(planned_step)
            continue
        annotated_step = replace(
            planned_step,
            instructions=_append_report_disposition_instruction(
                planned_step.instructions,
                report_disposition=report_disposition,
                ui_language=ui_language,
            ),
        )
        updated_steps.append(annotated_step)
        changed = changed or annotated_step.instructions != planned_step.instructions
    return tuple(updated_steps) if changed else planned_steps


def _append_report_disposition_instruction(
    instructions: str,
    *,
    report_disposition: str,
    ui_language: str | None,
) -> str:
    additions = (
        {
            "per_source_sections": "Write the report as one clear section per source.",
            "synthesized_overview": "Write the report as one synthesized overview across all sources.",
            "both": (
                "Write source-specific sections and end with a synthesized "
                "conclusion across all sources."
            ),
        }
        if ui_language == "en"
        else {
            "per_source_sections": "Skriv rapporten som ett tydligt avsnitt per källa.",
            "synthesized_overview": "Skriv rapporten som en samlad översikt över alla källor.",
            "both": (
                "Skriv källspecifika avsnitt och avsluta med en samlad "
                "slutsats över alla källor."
            ),
        }
    )
    addition = additions.get(report_disposition)
    if addition is None or addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


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
