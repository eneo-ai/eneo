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

from dataclasses import dataclass
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
    CapabilityRow.DOCUMENT_TO_STRUCTURED_REPORT: "buildable",
    CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE: "buildable",
    CapabilityRow.DOCUMENT_TO_DOCX_CREATE: "buildable",
    CapabilityRow.DOCUMENT_TO_PDF_REPORT: "buildable",
    CapabilityRow.AUDIO_TRANSCRIPTION: "buildable",
    CapabilityRow.COMPARISON: "buildable",
    CapabilityRow.SECTIONED_FORM_INTAKE: "buildable",
    CapabilityRow.UNDERLAG_TILL_TEXT: "buildable",
    # Runtime-only: the AI Builder authoring enums cannot emit HTTP steps.
    CapabilityRow.HTTP_POST_CALL: "gap",
    CapabilityRow.HTTP_GET_CALL: "gap",
}


def expected_state(row: CapabilityRow) -> MatrixRowState:
    return _EXPECTED_MATRIX_STATE[row]


class CoverageRequirement(str, Enum):
    """How strongly a buildable row must cover a complexity column.

    - REQUIRED: the row must have a golden whose shape derives this column.
    - ALLOWED: a golden may cover it (and it still counts toward the global
      column total) but the row does not have to.
    - NOT_APPLICABLE: the column is structurally impossible for this row, so a
      golden that derives it is a hard error.
    """

    REQUIRED = "required"
    ALLOWED = "allowed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RowComplexityPolicy:
    """Per-row coverage policy: the two complexity columns plus any
    non-complexity column the row must always carry.

    Encodes that some capabilities are inherently single-step (advanced is a
    forced graft) and some inherently multi-step (a basic single-step version is
    a contradiction), so "basic AND advanced on every row" is not a uniform
    contract. `required_columns` pins composition concepts whose defining shape
    is not a complexity grade (e.g. underlag_till_text -> JSON_IN_JSON_OUT_PIPE);
    any remaining column is governed by the global per-column threshold.
    """

    basic_single_step: CoverageRequirement
    advanced_multi_capability: CoverageRequirement
    # Non-complexity columns this row must also cover. Used for composition
    # concepts whose defining shape is not a complexity grade — e.g.
    # underlag_till_text requires JSON_IN_JSON_OUT_PIPE so its golden cannot
    # silently vanish.
    required_columns: frozenset[CompositionColumn] = frozenset()

    def requirement_for(self, column: CompositionColumn) -> CoverageRequirement:
        if column is CompositionColumn.BASIC_SINGLE_STEP:
            return self.basic_single_step
        if column is CompositionColumn.ADVANCED_MULTI_CAPABILITY:
            return self.advanced_multi_capability
        # Only the two complexity columns are graded here; a row's
        # `required_columns` set governs any non-complexity column it must carry.
        return CoverageRequirement.ALLOWED


_REQ = CoverageRequirement.REQUIRED
_OPT = CoverageRequirement.ALLOWED
_NA = CoverageRequirement.NOT_APPLICABLE

# Only buildable rows carry a policy. Gap rows are handled by the gap ratchet;
# planned rows gain a policy when they are promoted to buildable.
_ROW_COMPLEXITY_POLICIES: dict[CapabilityRow, RowComplexityPolicy] = {
    CapabilityRow.SUMMARIZE_TEXT: RowComplexityPolicy(_REQ, _OPT),
    CapabilityRow.EXTRACT_STRUCTURED_FIELDS: RowComplexityPolicy(_REQ, _OPT),
    CapabilityRow.DOCUMENT_TO_STRUCTURED_REPORT: RowComplexityPolicy(_REQ, _REQ),
    CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE: RowComplexityPolicy(_REQ, _REQ),
    CapabilityRow.DOCUMENT_TO_DOCX_CREATE: RowComplexityPolicy(_REQ, _OPT),
    CapabilityRow.DOCUMENT_TO_PDF_REPORT: RowComplexityPolicy(_REQ, _OPT),
    CapabilityRow.AUDIO_TRANSCRIPTION: RowComplexityPolicy(_REQ, _OPT),
    CapabilityRow.COMPARISON: RowComplexityPolicy(_REQ, _REQ),
    CapabilityRow.SECTIONED_FORM_INTAKE: RowComplexityPolicy(_REQ, _REQ),
    CapabilityRow.UNDERLAG_TILL_TEXT: RowComplexityPolicy(
        _NA,
        _OPT,
        required_columns=frozenset({CompositionColumn.JSON_IN_JSON_OUT_PIPE}),
    ),
}


def row_complexity_policy(row: CapabilityRow) -> RowComplexityPolicy | None:
    """The complexity policy for a buildable row, or None if it has no policy."""
    return _ROW_COMPLEXITY_POLICIES.get(row)
