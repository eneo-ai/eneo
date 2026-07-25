"""Server-owned derivation of architecture commit drafts.

The planner may decide that the conversation is ready to commit, but it
should not have to freehand low-level Flow Capability Manifest tuples.
This module derives the semantic architecture draft from deterministic
`PlanningState.resolved_slots` whenever the core slots are available.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_aggregation_intent import (
    derive_aggregation_intent_from_slots,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import derive_output_mode
from eneo.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    StepOutputMode,
    StepTriple,
)
from eneo.flows.enums import (
    AIBuilderInputType,
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import (
    InputType as AuthoringInputType,
)
from eneo.flows.flow_authoring_spec import (
    OutputType as AuthoringOutputType,
)
from eneo.flows.flow_capability_manifest import resolve_capability_for_tuple


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
                input_type=AIBuilderInputType(input_type.value),
                output_type=output_type.value,
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
    )


def _input_type_from_state(state: PlanningState) -> FlowInputType | None:
    slot = state.resolved_slots.get("primary_runtime_input")
    if slot is None:
        return None
    return flow_input_type_from_primary_runtime_input_value(slot.value)


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
    docx_mode = state.resolved_slots.get("docx_output_mode")
    document_delivery_mode = (
        "template_fill"
        if output_type is FlowOutputType.DOCX
        and docx_mode is not None
        and docx_mode.value == "template_fill_docx"
        else "generated"
    )
    return FlowOutputMode(
        derive_output_mode(
            input_type=AuthoringInputType(input_type.value),
            output_type=AuthoringOutputType(output_type.value),
            document_delivery_mode=document_delivery_mode,
        ).value
    )


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
    if output_type is FlowOutputType.PDF:
        return "document_to_pdf_report"
    if input_type in {FlowInputType.DOCUMENT, FlowInputType.FILE}:
        return "document_to_structured_report"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.JSON:
        return "extract_structured_fields"
    if input_type is FlowInputType.TEXT and output_type is FlowOutputType.TEXT:
        return "summarize_text"
    return None


def _step_output_mode_value(output_mode: FlowOutputMode) -> StepOutputMode | None:
    match output_mode:
        case FlowOutputMode.PASS_THROUGH:
            return "pass_through"
        case FlowOutputMode.TRANSCRIBE_ONLY:
            return "transcribe_only"
        case FlowOutputMode.TEMPLATE_FILL:
            return "template_fill"
        case FlowOutputMode.RENDER_VERBATIM:
            return "render_verbatim"
        case FlowOutputMode.COMPOSE_TEXT | FlowOutputMode.HTTP_POST:
            # Neither is an authored planner value: compose_text is the implicit
            # default and http_post is server-injected, so the planner's
            # vocabulary has no member for either.
            return None


__all__ = [
    "derive_architecture_commit_draft",
    "flow_input_type_from_primary_runtime_input_value",
]
