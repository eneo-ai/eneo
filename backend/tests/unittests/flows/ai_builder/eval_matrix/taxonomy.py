"""Capability and composition taxonomies for the AI Builder eval matrix.

`CapabilityRow` is *what kind of flow* the builder is asked for;
`CompositionColumn` is *how the steps compose*. The matrix is their product.

`EXPECTED_MATRIX_STATE` is the ratchet: every row is classified once as

- ``buildable`` — the AI Builder can author this shape; a golden must prove it;
- ``gap`` — the runtime supports it but the AI Builder authoring enums cannot
  express it (HTTP today); a `KnownCapabilityGap` records the evidence;
- ``planned`` — buildable in principle, not yet seeded with a golden.

A planned row is visible, enforced debt, not a silent omission: the suite fails
if a planned row gains a golden without being promoted here, and fails if a gap
row becomes authorable.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, get_args

MatrixRowState = Literal["buildable", "gap", "planned"]
MATRIX_ROW_STATES: frozenset[str] = frozenset(get_args(MatrixRowState))


class CapabilityRow(str, Enum):
    SUMMARIZE_TEXT = "summarize_text"
    EXTRACT_STRUCTURED_FIELDS = "extract_structured_fields"
    DOCUMENT_TO_STRUCTURED_REPORT = "document_to_structured_report"
    DOCUMENT_TO_DOCX_TEMPLATE = "document_to_docx_template"
    DOCUMENT_TO_DOCX_CREATE = "document_to_docx_create"
    DOCUMENT_TO_PDF_REPORT = "document_to_pdf_report"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    MULTI_STEP_QUALITY_CHAIN = "multi_step_quality_chain"
    COMPARISON = "comparison"
    SECTIONED_FORM_INTAKE = "sectioned_form_intake"
    HTTP_POST_CALL = "http_post_call"
    HTTP_GET_CALL = "http_get_call"
    UNDERLAG_TILL_TEXT = "underlag_till_text"


class CompositionColumn(str, Enum):
    FORM_FIELDS_DECLARE_ONLY = "form_fields_declare_only"
    FORM_FIELDS_CHAIN = "form_fields_chain"
    JSON_IN_JSON_OUT_PIPE = "json_in_json_out_pipe"
    ALL_STEPS_MULTI_REFERENCE = "all_steps_multi_reference"
    BASIC_SINGLE_STEP = "basic_single_step"
    ADVANCED_MULTI_CAPABILITY = "advanced_multi_capability"
    EDIT_PATH = "edit_path"


_EXPECTED_MATRIX_STATE: dict[CapabilityRow, MatrixRowState] = {
    CapabilityRow.SUMMARIZE_TEXT: "buildable",
    CapabilityRow.EXTRACT_STRUCTURED_FIELDS: "buildable",
    CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE: "buildable",
    CapabilityRow.DOCUMENT_TO_DOCX_CREATE: "buildable",
    CapabilityRow.SECTIONED_FORM_INTAKE: "buildable",
    CapabilityRow.MULTI_STEP_QUALITY_CHAIN: "buildable",
    # Buildable in principle, not yet seeded with a golden.
    CapabilityRow.DOCUMENT_TO_STRUCTURED_REPORT: "planned",
    CapabilityRow.DOCUMENT_TO_PDF_REPORT: "planned",
    CapabilityRow.AUDIO_TRANSCRIPTION: "planned",
    CapabilityRow.COMPARISON: "planned",
    CapabilityRow.UNDERLAG_TILL_TEXT: "planned",
    # Runtime-only: the AI Builder authoring enums cannot emit HTTP steps.
    CapabilityRow.HTTP_POST_CALL: "gap",
    CapabilityRow.HTTP_GET_CALL: "gap",
}


def expected_state(row: CapabilityRow) -> MatrixRowState:
    return _EXPECTED_MATRIX_STATE[row]
