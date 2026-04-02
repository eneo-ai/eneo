from __future__ import annotations

from typing import Any

from intric.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    resolve_citation_mode,
)


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
    output_type: str | None,
    output_mode: str | None,
) -> str | None:
    if output_type == "docx":
        return "template_fill" if output_mode == "template_fill" else "generated"
    if output_type == "pdf":
        return "generated"
    return None


def is_citation_capable_step(
    *,
    output_type: str,
    output_mode: str,
    output_config: Any,
) -> bool:
    citation_mode = resolve_citation_mode(output_config)
    if citation_mode != CITATION_MODE_INLINE_INREF_SIDECAR:
        return False
    return output_type == "text" and output_mode not in {"template_fill", "transcribe_only"}
