"""Server-owned derivation of architecture commit drafts.

The planner may decide that the conversation is ready to commit, but it
should not have to freehand low-level Flow Capability Manifest tuples.
This module derives the semantic architecture draft from deterministic
`PlanningState.resolved_slots` whenever the core slots are available.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_aggregation_intent import (
    derive_aggregation_intent_from_slots,
    report_disposition_is_relevant,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import derive_output_mode
from eneo.flows.ai_builder.ai_builder_result_contract import derive_result_contract
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    FLOW_INPUT_DOCUMENT_UPLOAD,
    PATTERN_REGISTRY,
    PREPARE_TEMPLATE_CONTENT_STEP,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
    pattern_chain_steps,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    ReportDisposition,
    StepTriple,
)
from eneo.flows.enums import (
    FlowAuthoringInputType,
    FlowAuthoringOutputMode,
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import (
    InputType as AuthoringInputType,
)
from eneo.flows.flow_authoring_spec import OutputMode as AuthoringOutputMode
from eneo.flows.flow_authoring_spec import (
    OutputType as AuthoringOutputType,
)
from eneo.flows.flow_capability_manifest import resolve_capability_for_tuple

_AUDIO_ARTIFACT_PATTERN_ID = "audio_to_artifact_report"
_FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID = "form_field_runtime_inputs"
_AUDIO_PATTERN_IDS_WITH_FORM_FIELDS = frozenset(
    {
        "audio_transcription",
        _AUDIO_ARTIFACT_PATTERN_ID,
        _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID,
    }
)
_AUDIO_PATTERN_CHAIN_STEPS = frozenset(
    {FLOW_INPUT_AUDIO_TRANSCRIPTION, TERMINAL_ARTIFACT_STEP}
)
_DOCX_TEMPLATE_PATTERN_ID = "document_to_docx_template"
_DOCX_TEMPLATE_PATTERN_CHAIN_STEPS = frozenset(
    {
        FLOW_INPUT_DOCUMENT_UPLOAD,
        EXTRACT_TEMPLATE_VARIABLES_STEP,
        PREPARE_TEMPLATE_CONTENT_STEP,
        TEMPLATE_FILL_DOCX_STEP,
    }
)
CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(
    {"primary_runtime_input", "terminal_output"}
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
        "summarize_text",
        "text_to_artifact_report",
    }
)


def derive_architecture_commit_draft(
    state: PlanningState,
) -> ArchitectureCommitDraft | None:
    """Derive a legal architecture draft from resolved planning slots.

    Returns `None` when the core slots are not resolved or when a slot
    value is outside the deterministic mapping. The caller can then fall
    back to the normal evaluator/repair path.
    """
    input_type = _input_type_from_state(state)
    output_type = _output_type_from_state(state)
    if input_type is None or output_type is None:
        return None

    output_mode = _output_mode_from_state(state, input_type, output_type)
    capabilities = resolve_capability_for_tuple(
        input_source=FlowInputSource.FLOW_INPUT,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
    )
    if capabilities is None:
        return None

    chosen_patterns = _chosen_patterns_for_state(
        state=state,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
    )
    if not chosen_patterns:
        return None

    step_output_mode = _step_output_mode_value(output_mode)
    if step_output_mode is None:
        return None

    return ArchitectureCommitDraft(
        tuples_chain=[
            StepTriple(
                input_type=FlowAuthoringInputType(input_type.value),
                output_type=output_type,
                output_mode=step_output_mode,
            )
        ],
        chosen_patterns=chosen_patterns,
        required_capabilities=[capability.id for capability in capabilities],
        aggregation_intent=derive_aggregation_intent_from_slots(
            state,
            document_material_input=input_type
            in {FlowInputType.DOCUMENT, FlowInputType.FILE},
        ),
        report_disposition=_report_disposition_from_state(state),
    )


def architecture_required_slot_names(state: PlanningState) -> frozenset[str]:
    """Slots a created flow's architecture must have before it can commit.

    The purpose is architectural for exactly one shape: an audio flow whose
    terminal output is text either delivers the transcript itself or a written
    result derived from it, and those are different topologies. Everywhere
    else the purpose shapes content, not structure.
    """

    if (
        _input_type_from_state(state) is FlowInputType.AUDIO
        and _output_type_from_state(state) is FlowOutputType.TEXT
    ):
        return CORE_ARCHITECTURAL_SLOTS | {"post_processing_goal"}
    return CORE_ARCHITECTURAL_SLOTS


def architecture_commit_hints_are_supported(
    architecture: ArchitectureCommitDraft,
) -> bool:
    """Whether one committed pattern envelope has a supported compiler shape."""

    if not architecture.tuples_chain:
        return False
    first = architecture.tuples_chain[0]
    last = architecture.tuples_chain[-1]
    return architecture_hints_are_supported(
        runtime_input_type=AuthoringInputType(first.input_type.value),
        final_output_type=AuthoringOutputType(last.output_type.value),
        final_output_mode=AuthoringOutputMode(last.output_mode.value),
        pattern_ids=tuple(architecture.chosen_patterns),
        chain_steps=pattern_chain_steps(architecture.chosen_patterns),
    )


def architecture_hints_are_supported(
    *,
    runtime_input_type: AuthoringInputType,
    final_output_type: AuthoringOutputType,
    final_output_mode: AuthoringOutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    """Validate the pattern envelope used by create assembly."""

    if not pattern_ids and not chain_steps:
        return True
    if not chain_steps and set(pattern_ids) <= _SUPPORTED_STRUCTURAL_PATTERN_IDS:
        return True
    if runtime_input_type is AuthoringInputType.AUDIO:
        pattern_id_set = set(pattern_ids)
        if (
            _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID in pattern_id_set
            and _AUDIO_ARTIFACT_PATTERN_ID not in pattern_id_set
        ):
            return False
        return (
            pattern_id_set <= _AUDIO_PATTERN_IDS_WITH_FORM_FIELDS
            and set(chain_steps) <= _AUDIO_PATTERN_CHAIN_STEPS
        )
    if (
        runtime_input_type in {AuthoringInputType.DOCUMENT, AuthoringInputType.FILE}
        and final_output_type is AuthoringOutputType.DOCX
        and final_output_mode is AuthoringOutputMode.TEMPLATE_FILL
    ):
        pattern_id_set = set(pattern_ids)
        if (
            _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID in pattern_id_set
            and _DOCX_TEMPLATE_PATTERN_ID not in pattern_id_set
        ):
            return False
        return (
            pattern_id_set
            <= {
                _DOCX_TEMPLATE_PATTERN_ID,
                _FORM_FIELD_RUNTIME_INPUTS_PATTERN_ID,
            }
            and set(chain_steps) <= _DOCX_TEMPLATE_PATTERN_CHAIN_STEPS
        )
    return False


def _input_type_from_state(state: PlanningState) -> FlowInputType | None:
    value = state.commit_grade_slot_value("primary_runtime_input")
    if value is None:
        return None
    return flow_input_type_from_primary_runtime_input_value(value)


def flow_input_type_from_primary_runtime_input_value(
    value: str,
) -> FlowInputType | None:
    """Map persisted primary-runtime-input slot values to Flow input types."""

    return {
        "audio": FlowInputType.AUDIO,
        "document": FlowInputType.DOCUMENT,
        "documents": FlowInputType.DOCUMENT,
        "file": FlowInputType.FILE,
        "json": FlowInputType.JSON,
        "text": FlowInputType.TEXT,
        # The runtime has one primary input type. `file` is the closest
        # engine primitive for mixed pasted/uploaded material.
        "text_and_documents": FlowInputType.FILE,
    }.get(value)


def _output_type_from_state(state: PlanningState) -> FlowOutputType | None:
    value = state.commit_grade_slot_value("terminal_output")
    if value is None:
        return None
    return {
        "docx": FlowOutputType.DOCX,
        "docx_document": FlowOutputType.DOCX,
        "json": FlowOutputType.JSON,
        "pdf": FlowOutputType.PDF,
        "pdf_document": FlowOutputType.PDF,
        "text": FlowOutputType.TEXT,
        "structured_json": FlowOutputType.JSON,
        "structured_text": FlowOutputType.TEXT,
    }.get(value)


def _output_mode_from_state(
    state: PlanningState,
    input_type: FlowInputType,
    output_type: FlowOutputType,
) -> FlowOutputMode:
    if input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT:
        # `transcribe_only` is a step pathway, not a flow envelope: the
        # capability manifest defines it as one AUDIO -> TEXT step. It is the
        # flow's terminal mode only when the transcript itself is the result.
        # Any further work is a model-owned semantic step writing the terminal
        # text, exactly as for a JSON, PDF or DOCX terminal.
        return (
            FlowOutputMode.TRANSCRIBE_ONLY
            if _flow_stops_after_transcription(state)
            else FlowOutputMode.PASS_THROUGH
        )
    docx_mode = state.commit_grade_slot_value("docx_output_mode")
    document_delivery_mode = (
        "template_fill"
        if output_type is FlowOutputType.DOCX and docx_mode == "template_fill_docx"
        else "generated"
    )
    return FlowOutputMode(
        derive_output_mode(
            input_type=AuthoringInputType(input_type.value),
            output_type=AuthoringOutputType(output_type.value),
            document_delivery_mode=document_delivery_mode,
        ).value
    )


def _flow_stops_after_transcription(state: PlanningState) -> bool:
    contract = derive_result_contract(state)
    return contract is not None and contract.stops_after_primary_operation


def _chosen_patterns_for_state(
    *,
    state: PlanningState,
    input_type: FlowInputType,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> list[str]:
    pattern_ids: list[str] = []
    primary = _primary_pattern_id(state, input_type, output_type, output_mode)
    if primary is None:
        return []
    pattern_ids.append(primary)

    runtime_metadata = state.commit_grade_slot_value("runtime_metadata_fields")
    if (
        runtime_metadata is not None
        and runtime_metadata != "no_extra_metadata"
        and "form_field_runtime_inputs" not in pattern_ids
    ):
        pattern_ids.append("form_field_runtime_inputs")

    return [
        pattern_id
        for pattern_id in pattern_ids
        if pattern_id in PATTERN_REGISTRY
        and PATTERN_REGISTRY[pattern_id].polarity == "positive"
    ]


def _primary_pattern_id(
    state: PlanningState,
    input_type: FlowInputType,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> str | None:
    if output_mode is FlowOutputMode.TEMPLATE_FILL and input_type in {
        FlowInputType.DOCUMENT,
        FlowInputType.FILE,
    }:
        return "document_to_docx_template"
    if input_type is FlowInputType.JSON and output_type is FlowOutputType.JSON:
        return "json_to_structured_payload"
    if input_type is FlowInputType.JSON and output_type in {
        FlowOutputType.DOCX,
        FlowOutputType.PDF,
    }:
        return "json_to_artifact_report"
    if (
        input_type is FlowInputType.AUDIO
        and output_type is FlowOutputType.TEXT
        and output_mode is FlowOutputMode.TRANSCRIBE_ONLY
    ):
        return "audio_transcription"
    if input_type is FlowInputType.AUDIO:
        return "audio_to_artifact_report"
    if input_type is FlowInputType.TEXT and output_type in {
        FlowOutputType.DOCX,
        FlowOutputType.PDF,
    }:
        return "text_to_artifact_report"
    if output_type is FlowOutputType.PDF:
        return "document_to_pdf_report"
    if input_type in {FlowInputType.DOCUMENT, FlowInputType.FILE}:
        return "document_to_structured_report"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.JSON:
        return "extract_structured_fields"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.TEXT:
        return "summarize_text"
    return None


def _report_disposition_from_state(state: PlanningState) -> ReportDisposition | None:
    value = state.commit_grade_slot_value("report_disposition")
    if not report_disposition_is_relevant(
        primary_runtime_input=state.commit_grade_slot_value("primary_runtime_input"),
        terminal_output=state.commit_grade_slot_value("terminal_output"),
        document_material_scope=state.commit_grade_slot_value(
            "document_material_scope"
        ),
        docx_output_mode=state.commit_grade_slot_value("docx_output_mode"),
        unresolved_values_are_relevant=False,
    ):
        return None
    match value:
        case "per_source_sections" | "synthesized_overview" | "both":
            return value
        case _:
            return None


def _step_output_mode_value(
    output_mode: FlowOutputMode,
) -> FlowAuthoringOutputMode | None:
    if output_mode is FlowOutputMode.HTTP_POST:
        return None
    return FlowAuthoringOutputMode(output_mode.value)


__all__ = [
    "CORE_ARCHITECTURAL_SLOTS",
    "architecture_commit_hints_are_supported",
    "architecture_hints_are_supported",
    "architecture_required_slot_names",
    "derive_architecture_commit_draft",
    "flow_input_type_from_primary_runtime_input_value",
]
