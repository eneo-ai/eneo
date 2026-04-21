"""AI Builder Pattern Registry — planner-strategy archetypes.

Phase A.4 scaffold. A `Pattern` is a structural, planner-facing
archetype: a shape the planner may propose or avoid. It is **not**
engine truth (that's the FCM) and it carries **no user-facing copy**
(that's Question Catalog, Phase A.4b).

Each `Pattern` captures:

- `examples` / `negative_examples` / `retrieval_hints` — structural
  descriptors the planner can match against user intent (e.g.
  `"single-step summarize"`, `"avoid audio+template_fill"`). These are
  deliberately terse, non-localized tokens; no prose.
- `required_architectural_slots` — slot names from
  `ai_builder_resolved_requirements.py` that this archetype's
  discovery must resolve before the planner can commit to it.
- `question_template_ids` — forward-references the Question Catalog
  (A.4b). Resolution is pinned by an A.5 CI test once the catalog lands.
- `polarity` — `"positive"` archetypes are recommended paths;
  `"negative"` archetypes are anti-patterns grounded in FCM truth so
  the knowledge pack can tell the planner "don't propose this shape".

`PATTERN_REGISTRY_VERSION` starts at `1`. Phase A is an unpublished
epoch — the version is not persisted by any consumer yet. Phase B+
publishes the version; after that, any pattern-surface change bumps
it by one alongside a fingerprint update (analogous to A.3's FCM
bump-discipline, deferred to A.6 for the public API).

Out of scope for A.4:
- Public API (`find_pattern_candidates`, `render_knowledge_pack`) → A.6
- `importlinter` rule 3 (pattern_registry imports FCM + Question
  Catalog only) → A.5
- Consumer rewire (`recipe_selector.py`, `knowledge_pack_create.py`) → Phase B
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

PATTERN_REGISTRY_VERSION: int = 1

PatternPolarity = Literal["positive", "negative"]
_VALID_POLARITIES: frozenset[str] = frozenset({"positive", "negative"})


@dataclass(frozen=True, slots=True)
class Pattern:
    """Structural planner-strategy archetype.

    Frozen + slotted: the registry is canonical; patterns must not be
    mutated after construction.

    Fields are structural only. No labels, descriptions, help text, or
    localized copy — those belong to the Question Catalog (A.4b) and
    product surfaces that render patterns to users.
    """

    id: str
    examples: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    negative_examples: tuple[str, ...]
    required_architectural_slots: tuple[str, ...]
    question_template_ids: tuple[str, ...]
    polarity: PatternPolarity

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Pattern id must be a non-empty string")
        if self.polarity not in _VALID_POLARITIES:
            raise ValueError(
                f"Pattern polarity must be one of "
                f"{sorted(_VALID_POLARITIES)}; got {self.polarity!r}"
            )


def _pattern(
    *,
    id: str,
    examples: tuple[str, ...],
    retrieval_hints: tuple[str, ...],
    required_architectural_slots: tuple[str, ...],
    question_template_ids: tuple[str, ...] = (),
    negative_examples: tuple[str, ...] = (),
    polarity: PatternPolarity = "positive",
) -> Pattern:
    return Pattern(
        id=id,
        examples=examples,
        retrieval_hints=retrieval_hints,
        negative_examples=negative_examples,
        required_architectural_slots=required_architectural_slots,
        question_template_ids=question_template_ids,
        polarity=polarity,
    )


_POSITIVE_PATTERNS: tuple[Pattern, ...] = (
    _pattern(
        id="summarize_text",
        examples=(
            "single-step text in, text out",
            "one-shot summarization",
        ),
        retrieval_hints=(
            "summarize summary summera sammanfatta",
            "input_type=text output_type=text output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
        ),
    ),
    _pattern(
        id="extract_structured_fields",
        examples=(
            "text in, JSON out via form fields",
            "structured extraction of named fields",
        ),
        retrieval_hints=(
            "extract fields form structured json schema",
            "input_type=text output_type=json output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
        ),
    ),
    _pattern(
        id="document_to_structured_report",
        examples=(
            "document in, text or JSON report out over scoped material",
            "report synthesis over uploaded documents without structured intermediate",
        ),
        retrieval_hints=(
            "document analysis report",
            "input_type=document output_type=text output_mode=pass_through",
            "input_type=document output_type=json output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
    ),
    _pattern(
        id="document_to_docx_template",
        examples=(
            "document in, DOCX out via template_fill",
            "fill a DOCX template from document-derived inputs",
        ),
        retrieval_hints=(
            "docx template generate report document",
            "output_type=docx output_mode=template_fill",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
            "docx_output_mode",
            "document_material_scope",
        ),
    ),
    _pattern(
        id="document_to_pdf_report",
        examples=(
            "document in, PDF out via generation",
            "PDF report synthesized from document inputs",
        ),
        retrieval_hints=(
            "pdf report generate document",
            "output_type=pdf output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
            "pdf_generation_mode",
            "document_material_scope",
        ),
    ),
    _pattern(
        id="audio_transcription",
        examples=(
            "audio in, text out via transcribe_only",
            "single-step audio transcription",
        ),
        retrieval_hints=(
            "audio transcribe transkribera transkription",
            "input_type=audio output_type=text output_mode=transcribe_only",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
        ),
    ),
    _pattern(
        id="multi_step_quality_chain",
        examples=(
            "multi-step pipeline with structured intermediate + quality polish",
            "document analysis chained into editorial quality pass",
        ),
        retrieval_hints=(
            "rich document workflow quality polish review chain multi step",
            "structured intermediate previous_step",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
            "structured_analysis_need",
        ),
    ),
    _pattern(
        id="comparison",
        examples=(
            "compare two uploaded documents and produce a structured comparison",
            "document-to-document comparison with scoped material",
        ),
        retrieval_hints=(
            "compare comparison jämför jamfor diff",
            "input_type=document output_type=json output_mode=pass_through",
            "input_type=document output_type=text output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
    ),
    _pattern(
        id="sectioned_form_intake",
        examples=(
            "multi-section form-field intake at flow input",
            "structured headings captured as form_fields on the first step",
        ),
        retrieval_hints=(
            "sectioned form intake rubriker sections headings",
            "input_type=text output_type=text output_mode=pass_through",
            "input_type=text output_type=json output_mode=pass_through",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
        ),
    ),
)

_NEGATIVE_PATTERNS: tuple[Pattern, ...] = (
    _pattern(
        id="image_input_pipeline",
        examples=(),
        retrieval_hints=("avoid image input",),
        negative_examples=(
            "input_type=image pass_through",
            "image upload at runtime as primary input",
        ),
        required_architectural_slots=(),
        polarity="negative",
    ),
    _pattern(
        id="template_fill_non_docx",
        examples=(),
        retrieval_hints=("avoid template_fill without docx output",),
        negative_examples=(
            "output_mode=template_fill output_type=text",
            "output_mode=template_fill output_type=pdf",
            "output_mode=template_fill output_type=json",
        ),
        required_architectural_slots=(),
        polarity="negative",
    ),
)


def _build_registry() -> Mapping[str, Pattern]:
    patterns: tuple[Pattern, ...] = _POSITIVE_PATTERNS + _NEGATIVE_PATTERNS
    registry: dict[str, Pattern] = {}
    for pattern in patterns:
        if pattern.id in registry:
            raise ValueError(f"Duplicate pattern id in seed: {pattern.id!r}")
        registry[pattern.id] = pattern
    return MappingProxyType(registry)


PATTERN_REGISTRY: Mapping[str, Pattern] = _build_registry()
