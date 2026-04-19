from intric.flows.ai_builder.ai_builder_step_capabilities import (
    BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE,
    BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE,
    is_citation_capable_step,
    resolve_document_generation_mode,
    resolve_final_output_artifact,
    resolve_runtime_input_mode,
    supports_step_io_mode_combo,
)
from intric.flows.citation_sidecar import CITATION_MODE_INLINE_INREF_SIDECAR
from intric.flows.enums import FlowInputType, FlowOutputMode, FlowOutputType


def test_resolve_runtime_input_mode_maps_supported_input_types() -> None:
    assert resolve_runtime_input_mode(FlowInputType.DOCUMENT) == "documents"
    assert resolve_runtime_input_mode("document") == "documents"
    assert resolve_runtime_input_mode("file") == "documents"
    assert resolve_runtime_input_mode("audio") == "audio"
    assert resolve_runtime_input_mode("text") == "text"
    assert resolve_runtime_input_mode("json") == "text"
    assert resolve_runtime_input_mode("image") is None
    assert resolve_runtime_input_mode("any") is None


def test_resolve_final_output_artifact_maps_all_flow_output_types() -> None:
    assert resolve_final_output_artifact(FlowOutputType.TEXT) == "structured_text"
    assert resolve_final_output_artifact("text") == "structured_text"
    assert resolve_final_output_artifact("json") == "structured_json"
    assert resolve_final_output_artifact("pdf") == "pdf_document"
    assert resolve_final_output_artifact("docx") == "docx_document"


def test_supports_step_io_mode_combo_handles_special_modes() -> None:
    assert (
        supports_step_io_mode_combo(
            input_type="audio",
            output_type="text",
            output_mode="transcribe_only",
        )
        is True
    )
    assert (
        supports_step_io_mode_combo(
            input_type="document",
            output_type="text",
            output_mode="transcribe_only",
        )
        is False
    )
    assert (
        supports_step_io_mode_combo(
            input_type="text",
            output_type="docx",
            output_mode="template_fill",
        )
        is True
    )
    assert (
        supports_step_io_mode_combo(
            input_type="text",
            output_type="pdf",
            output_mode="template_fill",
        )
        is False
    )


def test_resolve_document_generation_mode_handles_enum_inputs() -> None:
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.TEMPLATE_FILL,
        )
        == "template_fill"
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.DOCX,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        == "generated"
    )
    assert (
        resolve_document_generation_mode(
            output_type=FlowOutputType.PDF,
            output_mode=FlowOutputMode.PASS_THROUGH,
        )
        == "generated"
    )


def test_is_citation_capable_step_stays_narrow() -> None:
    assert (
        is_citation_capable_step(
            output_type="text",
            output_mode="pass_through",
            output_config={"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR},
        )
        is True
    )
    assert (
        is_citation_capable_step(
            output_type="text",
            output_mode="transcribe_only",
            output_config={"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR},
        )
        is False
    )
    assert (
        is_citation_capable_step(
            output_type="pdf",
            output_mode="pass_through",
            output_config={"citation_mode": CITATION_MODE_INLINE_INREF_SIDECAR},
        )
        is False
    )


def test_builder_runtime_input_capability_map_stays_in_sync_with_flow_input_enum() -> (
    None
):
    assert {item.value for item in FlowInputType} == set(
        BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE
    ) | {"image", "any"}


def test_builder_final_output_artifact_map_stays_in_sync_with_flow_output_enum() -> (
    None
):
    assert {item.value for item in FlowOutputType} == set(
        BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE
    )
