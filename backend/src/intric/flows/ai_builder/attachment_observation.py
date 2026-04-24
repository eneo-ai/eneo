"""Typed AttachmentObservation persisted in `builder_attachment_observations`.

An AttachmentObservation is **structured planning evidence** the AI Builder
planner consumes as architectural signal, not only compressed text.

Three tiers of content flow through one row:

1. **Classification** — `kind` (template, form, example output, reference,
   …) and `structure` flags (`has_placeholders`, `has_form_fields`,
   `has_tables`, …).
2. **Planner-facing signal** — `digest_text` (short readable summary),
   `likely_planner_implications` (pattern suggestions with confidence +
   rationale), `missing_info_cues`, `capability_relevance`, and
   `likely_questions_triggered` (IDs resolvable via `QUESTION_CATALOG`).
3. **Deterministic ground truth** — `DeterministicSignals` computed by
   pure Python (mime type, page count, heading tree, form fields,
   placeholder tokens, …). The LLM observation pass receives these as
   non-negotiable context and must not contradict them.

Each row is content-addressed within a tenant: identical uploads
deduplicate by `content_sha256`. The cache key `(tenant_id,
content_sha256, digest_version, fcm_version, pattern_registry_version)`
makes any prompt-surface, capability-surface, or pattern-surface bump
invalidate prior rows. `pattern_registry_version` is module-internal
hygiene in `planning_state` but is load-bearing here:
`capability_relevance` and `likely_questions_triggered` depend on the
pattern set in force at observation time, so a pattern-surface change
must not silently return cached observations against the old set.

`AttachmentObservation.model_dump(mode="json")` serializes a full
snapshot for the `observation_json` JSONB column;
`DeterministicSignals.model_dump(mode="json")` lives in
`deterministic_signals_json`. Save-path revalidation goes through
`validated_snapshot()` so container mutations (list appends, dict
sets) cannot silently poison the cache.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.flows.ai_builder.pattern_registry import PatternId
from intric.flows.flow_capability_manifest import CapabilityId

CONTENT_SHA256_HEX_LENGTH: int = 64

AttachmentKind = Literal[
    "template",
    "form",
    "example_output",
    "reference",
    "input_exemplar",
    "transcript",
    "spec",
    "policy",
]

StructuredFallbackMode = Literal["dense_text", "structural_schema"]


class _AttachmentObservationModel(BaseModel):
    """Strict base for every persisted attachment-observation model.

    `extra="forbid"` traps JSONB drift at load. `validate_assignment=True`
    re-runs validators on direct attribute reassignment. Container
    mutations (list appends, dict inserts) bypass the validators; the
    save path must call `AttachmentObservation.validated_snapshot`
    before writing so drift fails loudly instead of persisting.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AttachmentStructure(_AttachmentObservationModel):
    """Boolean flags describing the attachment's structural shape.

    `has_placeholders` / `has_form_fields` / `has_sections` / `has_tables`
    / `has_hierarchy` are populated directly from deterministic signals
    when possible. `has_unfilled_fields` requires semantic judgement
    and is set by the LLM observation pass.
    """

    has_placeholders: bool
    has_form_fields: bool
    has_sections: bool
    has_tables: bool
    has_hierarchy: bool
    has_unfilled_fields: bool


class PlannerImplication(_AttachmentObservationModel):
    """Pattern suggestion this attachment implies.

    `suggested_pattern_id` references a Pattern in the Pattern Registry;
    resolution is pinned by consumers (the critic verifies committed
    architecture against high-confidence implications).
    `confidence` is a 0..1 score. `reason` is a one-line LLM rationale.
    """

    suggested_pattern_id: PatternId
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("reason")
    @classmethod
    def _non_empty_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must be non-empty")
        return stripped


class StructuredFallback(_AttachmentObservationModel):
    """Richer alternative for inputs where the ~500-token digest loses
    too much detail.

    - `dense_text` — boilerplate-stripped prose packed dense (~2 KB
      cap). Used for PDFs with cover-page / TOC noise.
    - `structural_schema` — structural summary (headers, row counts,
      form-field list) in ~1 KB. Used when the document *is* the
      structure (forms, tables, templates).
    """

    mode: StructuredFallbackMode
    content: str


class Heading(_AttachmentObservationModel):
    """One heading in a document's structural tree (DOCX / Markdown / HTML)."""

    level: int = Field(ge=1, le=6)
    text: str


class FormFieldSignal(_AttachmentObservationModel):
    """One form-field extracted deterministically (DOCX / PDF form)."""

    name: str
    field_type: str
    default: Optional[str] = None
    placeholder: Optional[str] = None


class TableDimension(_AttachmentObservationModel):
    """One table's row/column count (pure structural signal)."""

    rows: int = Field(ge=0)
    cols: int = Field(ge=0)


class DeterministicSignals(_AttachmentObservationModel):
    """Mechanical signals extracted by pure Python before the LLM pass.

    Ground truth: the LLM observation prompt receives these and must
    not contradict them (no calling a 40-page document "one page").
    Fields unpopulated for a given mime type stay `None` or empty list.
    """

    mime_type: str
    extension: str
    size_bytes: int = Field(ge=0)
    page_count: Optional[int] = Field(default=None, ge=0)
    heading_tree: Optional[list[Heading]] = None
    section_count: Optional[int] = Field(default=None, ge=0)
    table_count: Optional[int] = Field(default=None, ge=0)
    table_dimensions: list[TableDimension] = Field(default_factory=list[TableDimension])
    form_fields: list[FormFieldSignal] = Field(default_factory=list[FormFieldSignal])
    placeholder_tokens: list[str] = Field(default_factory=list[str])
    is_scanned_pdf: Optional[bool] = None
    bullet_density: Optional[float] = Field(default=None, ge=0.0)
    spreadsheet_headers: Optional[list[str]] = None
    spreadsheet_column_types: Optional[list[str]] = None
    row_count: Optional[int] = Field(default=None, ge=0)
    duration_seconds: Optional[float] = Field(default=None, ge=0.0)
    channel_count: Optional[int] = Field(default=None, ge=0)
    language_hint: Optional[str] = None


class AttachmentObservation(_AttachmentObservationModel):
    """Structured planning evidence for one attachment.

    Identity fields `tenant_id` + `content_sha256` plus the three
    version stamps (`digest_version`, `fcm_version`,
    `pattern_registry_version`) form the cache key. A bump to any
    version invalidates prior rows.

    `likely_questions_triggered` carries `QuestionTemplate` IDs;
    resolution through `QUESTION_CATALOG` is the consumer's
    responsibility so observation rows stay small.
    """

    tenant_id: UUID
    content_sha256: str
    digest_version: int = Field(gt=0)
    fcm_version: int = Field(gt=0)
    pattern_registry_version: int = Field(gt=0)
    kind: AttachmentKind
    structure: AttachmentStructure
    digest_text: str
    structured_fallback: Optional[StructuredFallback] = None
    likely_planner_implications: list[PlannerImplication] = Field(
        default_factory=list[PlannerImplication]
    )
    missing_info_cues: list[str] = Field(default_factory=list[str])
    capability_relevance: dict[CapabilityId, float] = Field(
        default_factory=dict[str, float]
    )
    likely_questions_triggered: list[str] = Field(default_factory=list[str])
    token_count: int = Field(ge=0)

    @field_validator("content_sha256")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        if len(value) != CONTENT_SHA256_HEX_LENGTH:
            raise ValueError(
                f"content_sha256 must be {CONTENT_SHA256_HEX_LENGTH} "
                "lowercase hex characters"
            )
        for ch in value:
            if ch not in "0123456789abcdef":
                raise ValueError("content_sha256 must be lowercase hex")
        return value

    @field_validator("capability_relevance")
    @classmethod
    def _relevance_in_unit_interval(cls, value: dict[str, float]) -> dict[str, float]:
        for capability_id, score in value.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"capability_relevance[{capability_id!r}] = {score} "
                    "must be in [0, 1]"
                )
        return value

    def validated_snapshot(self) -> "AttachmentObservation":
        """Return a freshly revalidated copy suitable for the save path.

        Container-level mutations (list appends, dict inserts) bypass
        Pydantic's field validators. The save path calls this before
        writing so drift fails loudly instead of persisting.
        """
        return type(self).model_validate(self.model_dump(mode="json"))


__all__ = [
    "AttachmentKind",
    "AttachmentObservation",
    "AttachmentStructure",
    "CONTENT_SHA256_HEX_LENGTH",
    "DeterministicSignals",
    "FormFieldSignal",
    "Heading",
    "PlannerImplication",
    "StructuredFallback",
    "StructuredFallbackMode",
    "TableDimension",
]
