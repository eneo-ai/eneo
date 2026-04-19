from __future__ import annotations

from typing import Any

from intric.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    resolve_citation_mode,
)

BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE = {
    "document": "documents",
    "file": "documents",
    "audio": "audio",
    "text": "text",
    "json": "text",
}

BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE = {
    "text": "structured_text",
    "json": "structured_json",
    "pdf": "pdf_document",
    "docx": "docx_document",
}


def supports_step_io_mode_combo(
    *,
    input_type: str | None,
    output_type: str,
    output_mode: str,
) -> bool:
    if output_mode == "template_fill":
        return output_type == "docx"
    if output_mode == "transcribe_only":
        return input_type == "audio" and output_type == "text"
    return True


def resolve_document_generation_mode(
    *,
    output_type: Any,
    output_mode: Any,
) -> str | None:
    output_type_value = _as_str(output_type)
    output_mode_value = _as_str(output_mode)
    if output_type_value == "docx":
        return "template_fill" if output_mode_value == "template_fill" else "generated"
    if output_type_value == "pdf":
        return "generated"
    return None


def resolve_runtime_input_mode(input_type: Any) -> str | None:
    input_type_value = _as_str(input_type)
    if input_type_value is None:
        return None
    return BUILDER_RUNTIME_INPUT_MODE_BY_INPUT_TYPE.get(input_type_value)


def resolve_final_output_artifact(output_type: Any) -> str | None:
    output_type_value = _as_str(output_type)
    if output_type_value is None:
        return None
    return BUILDER_FINAL_OUTPUT_ARTIFACT_BY_OUTPUT_TYPE.get(output_type_value)


def is_citation_capable_step(
    *,
    output_type: str,
    output_mode: str,
    output_config: Any,
) -> bool:
    citation_mode = resolve_citation_mode(output_config)
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR:
        return False
    return output_type == "text" and output_mode not in {
        "template_fill",
        "transcribe_only",
    }


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))
