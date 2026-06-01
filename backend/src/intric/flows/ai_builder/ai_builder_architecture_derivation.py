"""Server-owned derivation of architecture commit drafts.

The planner may decide that the conversation is ready to commit, but it
should not have to freehand low-level Flow Capability Manifest tuples.
This module derives the semantic architecture draft from deterministic
`PlanningState.resolved_slots` whenever the core slots are available.
"""

from __future__ import annotations

from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommitDraft,
    PlanningState,
    StepTriple,
)
from intric.flows.enums import (
    AIBuilderInputType,
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_capability_manifest import resolve_capability_for_tuple

_DOCUMENT_MATERIAL_INPUT_TYPES = frozenset({FlowInputType.DOCUMENT, FlowInputType.FILE})
_DOCUMENT_SCOPE_AGGREGATION_VALUES = frozenset(
    {
        "multiple_documents_case",
        "multiple_pdfs_same_run",
        "same_run_multiple_documents",
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

    return ArchitectureCommitDraft(
        tuples_chain=[
            StepTriple(
                input_type=AIBuilderInputType(input_type.value),
                output_type=output_type.value,
                output_mode=output_mode.value,
            )
        ],
        chosen_patterns=chosen_patterns,
        required_capabilities=[capability.id for capability in capabilities],
        aggregation_intent=_aggregation_intent_from_state(
            state,
            input_type=input_type,
        ),
    )


def _input_type_from_state(state: PlanningState) -> FlowInputType | None:
    slot = state.resolved_slots.get("primary_runtime_input")
    if slot is None:
        return None
    return {
        "audio": FlowInputType.AUDIO,
        "documents": FlowInputType.DOCUMENT,
        "json": FlowInputType.JSON,
        "text": FlowInputType.TEXT,
        # The runtime has one primary input type. `file` is the closest
        # engine primitive for mixed pasted/uploaded material.
        "text_and_documents": FlowInputType.FILE,
    }.get(slot.value)


def _output_type_from_state(state: PlanningState) -> FlowOutputType | None:
    slot = state.resolved_slots.get("terminal_output")
    if slot is None:
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
    }.get(slot.value)


def _output_mode_from_state(
    state: PlanningState,
    input_type: FlowInputType,
    output_type: FlowOutputType,
) -> FlowOutputMode:
    if input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT:
        return FlowOutputMode.TRANSCRIBE_ONLY
    if output_type is FlowOutputType.DOCX:
        docx_mode = state.resolved_slots.get("docx_output_mode")
        if docx_mode is not None and docx_mode.value == "template_fill_docx":
            return FlowOutputMode.TEMPLATE_FILL
    return FlowOutputMode.PASS_THROUGH


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

    runtime_metadata = state.resolved_slots.get("runtime_metadata_fields")
    if (
        runtime_metadata is not None
        and runtime_metadata.value != "no_extra_metadata"
        and "form_field_runtime_inputs" not in pattern_ids
    ):
        pattern_ids.append("form_field_runtime_inputs")

    return [
        pattern_id
        for pattern_id in pattern_ids
        if pattern_id in PATTERN_REGISTRY
        and PATTERN_REGISTRY[pattern_id].polarity == "positive"
    ]


def _aggregation_intent_from_state(
    state: PlanningState,
    *,
    input_type: FlowInputType,
) -> AggregationIntent:
    comparison_scope = _resolved_slot_value(state, "comparison_scope")
    if comparison_scope == "same_run_compare":
        return "compare"
    if input_type in _DOCUMENT_MATERIAL_INPUT_TYPES and comparison_scope in {
        "same_run_multiple_documents",
        "multiple_documents_case",
    }:
        return "compare"

    document_scope = _resolved_slot_value(state, "document_material_scope")
    if (
        input_type in _DOCUMENT_MATERIAL_INPUT_TYPES
        and document_scope in _DOCUMENT_SCOPE_AGGREGATION_VALUES
    ):
        return "aggregate"

    return "linear"


def _resolved_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    return slot.value if slot is not None else None


def _primary_pattern_id(
    state: PlanningState,
    input_type: FlowInputType,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> str | None:
    if output_mode is FlowOutputMode.TEMPLATE_FILL:
        return "document_to_docx_template"
    if input_type is FlowInputType.JSON and output_type is FlowOutputType.JSON:
        return "json_to_structured_payload"
    if input_type is FlowInputType.JSON and output_type is FlowOutputType.TEXT:
        return "json_to_text_summary"
    if input_type is FlowInputType.JSON and output_type in {
        FlowOutputType.DOCX,
        FlowOutputType.PDF,
    }:
        return "json_to_artifact_report"
    if input_type is FlowInputType.AUDIO and output_type is FlowOutputType.TEXT:
        return "audio_transcription"
    if input_type is FlowInputType.AUDIO:
        return "audio_to_artifact_report"
    if input_type is FlowInputType.TEXT and output_type in {
        FlowOutputType.DOCX,
        FlowOutputType.PDF,
    }:
        return "text_to_artifact_report"
    structured_analysis = state.resolved_slots.get("structured_analysis_need")
    if (
        input_type in {FlowInputType.DOCUMENT, FlowInputType.FILE}
        and structured_analysis is not None
        and structured_analysis.value == "use_structured_analysis"
    ):
        return "multi_step_quality_chain"
    if output_type is FlowOutputType.PDF:
        return "document_to_pdf_report"
    if input_type in {FlowInputType.DOCUMENT, FlowInputType.FILE}:
        return "document_to_structured_report"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.JSON:
        return "extract_structured_fields"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.TEXT:
        return "summarize_text"
    return None


__all__ = ["derive_architecture_commit_draft"]
