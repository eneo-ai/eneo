"""AI Builder Pattern Registry — planner-strategy archetypes.

A `Pattern` is a structural, planner-facing archetype: a shape the
planner may propose or avoid. It is **not** engine truth (that's the
FCM) and it carries **no user-facing copy** (that's the Question
Catalog).

Each `Pattern` captures:

- `examples` / `negative_examples` / `retrieval_hints` — structural
  descriptors the planner can match against user intent (e.g.
  `"single-step summarize"`, `"avoid audio+template_fill"`). These are
  deliberately terse, non-localized tokens; no prose.
- `required_architectural_slots` — slot names from
  `ai_builder_slot_vocabulary.py` that this archetype's discovery
  must resolve before the planner can commit to it.
- `question_template_ids` — forward-references the Question Catalog.
  Resolution is pinned by
  `test_every_question_template_id_resolves_in_catalog` in
  `tests/unittests/flows/ai_builder/test_question_catalog.py`; any
  dangling reference fails CI.
- `polarity` — `"positive"` archetypes are recommended paths;
  `"negative"` archetypes are anti-patterns grounded in FCM truth so
  the knowledge pack can tell the planner "don't propose this shape".

`PATTERN_REGISTRY_VERSION` is the monotonic integer persisted alongside
plans and digests. Any pattern-surface change bumps it by one alongside
a fingerprint update, mirroring the FCM bump-discipline policy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from intric.flows.ai_builder.question_catalog import QUESTION_CATALOG, QuestionTemplate
from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY, FlowCapability

PATTERN_REGISTRY_VERSION: int = 4

PatternPolarity = Literal["positive", "negative"]
_VALID_POLARITIES: frozenset[str] = frozenset({"positive", "negative"})


@dataclass(frozen=True, slots=True)
class Pattern:
    """Structural planner-strategy archetype.

    Frozen + slotted: the registry is canonical; patterns must not be
    mutated after construction.

    Fields are structural only. No labels, descriptions, help text, or
    localized copy — those belong to the Question Catalog and product
    surfaces that render patterns to users.

    `chain_steps` is the ordered token sequence for patterns whose
    canonical realisation is multi-step. Each entry is a terse
    non-localized structural token (same vocabulary discipline as
    `examples` / `retrieval_hints`) naming one step in the chain;
    single-step shapes leave it empty.

    `recipe_sections` names the knowledge-pack recipe-section keys
    (`"transcription"`, `"docx_template"`, etc.) a pattern should
    activate when it wins a `find_pattern_candidates` scoring pass. The
    recipe selector reads this field instead of maintaining a separate
    pattern-id → section mapping. Patterns whose retrieval hints are too
    generic for reliable score-only triggering (and every negative
    pattern) leave it empty to opt out.
    """

    id: str
    examples: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    negative_examples: tuple[str, ...]
    required_architectural_slots: tuple[str, ...]
    question_template_ids: tuple[str, ...]
    polarity: PatternPolarity
    chain_steps: tuple[str, ...] = ()
    recipe_sections: tuple[str, ...] = ()

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
    chain_steps: tuple[str, ...] = (),
    recipe_sections: tuple[str, ...] = (),
) -> Pattern:
    return Pattern(
        id=id,
        examples=examples,
        retrieval_hints=retrieval_hints,
        negative_examples=negative_examples,
        required_architectural_slots=required_architectural_slots,
        question_template_ids=question_template_ids,
        polarity=polarity,
        chain_steps=chain_steps,
        recipe_sections=recipe_sections,
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
        question_template_ids=(
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
        ),
        recipe_sections=("json_pipeline",),
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
        recipe_sections=("document_analysis",),
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "docx_output_mode",
            "document_material_scope",
        ),
        chain_steps=(
            "flow_input_document_upload",
            "extract_template_variables_step",
            "template_fill_docx_step",
        ),
        recipe_sections=("docx_template",),
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "pdf_generation_mode",
            "document_material_scope",
        ),
        recipe_sections=("document_analysis",),
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
        ),
        recipe_sections=("transcription",),
    ),
    # `recipe_sections=()` on this pattern and on `sectioned_form_intake`
    # below is an intentional score-trigger opt-out, not a missed migration.
    # Their retrieval hints (`review`, `document`, `chain`, `form`,
    # `sections`, `headings`) overlap too heavily with generic planner
    # vocabulary; score-only activation would narrow "review my document"
    # onto the rich-workflow recipe. These recipes still reach the planner
    # through the phrase-aware signal paths in `ai_builder_recipe_selector`
    # (`extract_planner_pattern_recipe_signals`,
    # `extract_form_intake_recipe_signals`).
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
            "structured_analysis_need",
        ),
        chain_steps=(
            "flow_input_document_upload",
            "structured_extraction_step",
            "analysis_or_quality_review_step",
            "terminal_artifact_step",
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
        recipe_sections=("comparison",),
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
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
        ),
        chain_steps=(
            "flow_input_sectioned_form_fields",
            "compose_sections_step",
        ),
    ),
    # General-purpose counterpart to `sectioned_form_intake`. Matches any
    # flow shape where the user supplies one or more named runtime
    # variables alongside the primary input — e.g. "name + role +
    # description", "language + focus", "reference id + owning unit". The
    # sectioned variant stays for the narrower rubric-per-field shape.
    # `recipe_sections=()` because `form` / `fields` / `user` / `provides`
    # overlap heavily with generic planner vocabulary; score-only
    # activation would narrow unrelated prompts. The phrase-aware signal
    # paths in `ai_builder_recipe_selector` keep form-field recipes
    # routable through `extract_form_intake_recipe_signals` and
    # `extract_planner_pattern_recipe_signals`.
    _pattern(
        id="form_field_runtime_inputs",
        examples=(
            "runtime form_field variables alongside the primary input",
            "flow captures named parameters the user fills in per run",
        ),
        retrieval_hints=(
            "form fields formulärfält inmatningsfält runtime variables",
            "user provides enters fills parameters",
            "uses_form_fields variable_name",
        ),
        required_architectural_slots=(
            "primary_runtime_input",
            "terminal_output",
        ),
        question_template_ids=(
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


@dataclass(frozen=True, slots=True)
class PatternMatch:
    """Scored match from `find_pattern_candidates`.

    `score` is an integer token-hit count — higher means more
    retrieval-hint tokens from the pattern were found in the prompt. It
    is deliberately not a probability: patterns do not have a prior and
    the hint vocabulary is sparse, so a float would imply calibration
    that does not exist.
    """

    pattern: Pattern
    score: int


_WORD_PATTERN: re.Pattern[str] = re.compile(r"\w+", re.UNICODE)


def _tokenize_hints(retrieval_hints: tuple[str, ...]) -> frozenset[str]:
    """Collect distinct case-folded tokens from the retrieval hints.

    Each hint line is split on whitespace and case-folded so a multi-token
    hint like ``"summarize summary summera sammanfatta"`` contributes four
    matchable tokens. Duplicates across hint lines collapse because the
    scorer counts *distinct* overlap with the input text — if a pattern
    author lists ``"document analysis"`` and ``"input_type=document ..."``
    and ``"output_type=document ..."``, the single word ``document`` is
    still one signal, not three. Returning a frozenset makes the scorer
    invariant to how authors split their hint vocabulary across lines.
    """
    tokens: set[str] = set()
    for hint in retrieval_hints:
        for token in hint.casefold().split():
            if token:
                tokens.add(token)
    return frozenset(tokens)


def _word_tokens(text: str) -> frozenset[str]:
    """Case-folded Unicode word tokens extracted from `text`.

    Used as the membership set for hint matching so that a hint token
    `form` cannot spuriously match inside `information`, `step` inside
    `stepwise`, or `document` inside `documentation`. Unicode word chars
    preserve Swedish `å`, `ä`, `ö`.
    """
    return frozenset(
        match.group(0) for match in _WORD_PATTERN.finditer(text.casefold())
    )


def find_pattern_candidates(text: str) -> tuple[PatternMatch, ...]:
    """Score every positive pattern against `text` via retrieval-hint
    word-token overlap.

    Matching is on whole-word boundaries: a hint token like `form` only
    scores when `form` appears as a standalone word in `text`, never as
    a substring of `information`. Scoring counts *distinct* hint tokens
    that also appear in the input text, so a pattern that repeats a
    token across several hint phrases earns one point for it, not one
    per phrase — the number of distinct retrieval signals is the ranking
    signal, not authoring redundancy. Returns descending by score, ties
    broken by ascending pattern id for deterministic ordering across
    process restarts. Zero-score patterns are omitted so a no-signal
    prompt returns `()`. Negative patterns are never scored — they
    describe shapes to avoid, not candidates to propose; the knowledge
    pack surfaces them separately.
    """
    text_tokens = _word_tokens(text)
    if not text_tokens:
        return ()

    matches: list[PatternMatch] = []
    for pattern in PATTERN_REGISTRY.values():
        if pattern.polarity != "positive":
            continue
        hint_tokens = _tokenize_hints(pattern.retrieval_hints)
        score = len(hint_tokens & text_tokens)
        if score > 0:
            matches.append(PatternMatch(pattern=pattern, score=score))

    matches.sort(key=lambda match: (-match.score, match.pattern.id))
    return tuple(matches)


def question_template_ids_for_slot(pattern_id: str, slot: str) -> tuple[str, ...]:
    """Return the question-template ids this pattern declares for `slot`.

    Preserves the pattern's declaration order. Returns `()` when the
    pattern does not reference the slot. Raises `KeyError` for an unknown
    `pattern_id` — a typo in a caller should fail loudly rather than
    silently return empty.

    Slot names are not validated against
    `KNOWN_REQUIREMENT_SLOT_NAMES` here; the dangling-reference guard in
    `test_question_catalog.py::test_every_question_template_id_resolves_in_catalog`
    already covers that contract.
    """
    pattern = PATTERN_REGISTRY[pattern_id]
    if slot not in pattern.required_architectural_slots:
        return ()
    return tuple(qid for qid in pattern.question_template_ids if qid == slot)


_KNOWLEDGE_PACK_HEADER_CAPABILITIES = "## Flow capabilities (engine truth)"
_KNOWLEDGE_PACK_HEADER_POSITIVES = "## Planner patterns (positive archetypes)"
_KNOWLEDGE_PACK_HEADER_NEGATIVES = "## Planner patterns (negative archetypes — avoid)"
_KNOWLEDGE_PACK_HEADER_QUESTIONS = "## Discovery questions"


def _render_capability(cap: FlowCapability) -> str:
    lines: list[str] = [f"- {cap.id}: {cap.label}", f"  {cap.description}"]
    if cap.applies_to_tuples:
        tuple_lines = ", ".join(
            f"({source.value}, {input_type.value}, {output_type.value}, {output_mode.value})"
            for source, input_type, output_type, output_mode in cap.applies_to_tuples
        )
        lines.append(f"  applies_to: {tuple_lines}")
    return "\n".join(lines)


def _render_pattern(pattern: Pattern) -> str:
    lines: list[str] = [f"- {pattern.id}"]
    if pattern.polarity == "positive" and pattern.examples:
        lines.append("  examples: " + "; ".join(pattern.examples))
    if pattern.polarity == "negative" and pattern.negative_examples:
        lines.append("  avoid: " + "; ".join(pattern.negative_examples))
    if pattern.chain_steps:
        lines.append("  chain_steps: " + " -> ".join(pattern.chain_steps))
    if pattern.retrieval_hints:
        lines.append("  hints: " + "; ".join(pattern.retrieval_hints))
    if pattern.required_architectural_slots:
        lines.append(
            "  required_slots: " + ", ".join(pattern.required_architectural_slots)
        )
    if pattern.question_template_ids:
        lines.append(
            "  question_template_ids: " + ", ".join(pattern.question_template_ids)
        )
    return "\n".join(lines)


def _render_question_template(template: QuestionTemplate) -> str:
    lines: list[str] = [
        f"- {template.id}",
        f"  sv: {template.question_sv}",
        f"  en: {template.question_en}",
        f"  help_sv: {template.help_sv}",
        f"  help_en: {template.help_en}",
    ]
    for option in template.options:
        lines.append(f"    * {option.id} (value={option.value})")
        lines.append(f"      sv: {option.label_sv} — {option.description_sv}")
        lines.append(f"      en: {option.label_en} — {option.description_en}")
    return "\n".join(lines)


def render_knowledge_pack() -> str:
    """Render the LLM-facing knowledge pack.

    Sections are emitted in a fixed order with grep-friendly headers:
    builder-exposed capabilities, positive patterns, negative patterns,
    and the question templates referenced by any pattern's
    `question_template_ids` (rendered bilingually — the planner prompt
    consumes both sv and en copy).

    Every level is sorted by id so two invocations return byte-identical
    output. The determinism contract is pinned by
    `test_render_knowledge_pack_is_deterministic`; silent-drop guards
    cover every capability, pattern, and referenced question.
    """
    sections: list[str] = []

    sections.append(_KNOWLEDGE_PACK_HEADER_CAPABILITIES)
    builder_caps = sorted(
        (cap for cap in CAPABILITY_REGISTRY.values() if cap.exposure == "builder"),
        key=lambda cap: cap.id,
    )
    sections.extend(_render_capability(cap) for cap in builder_caps)

    positives = sorted(
        (p for p in PATTERN_REGISTRY.values() if p.polarity == "positive"),
        key=lambda p: p.id,
    )
    sections.append(_KNOWLEDGE_PACK_HEADER_POSITIVES)
    sections.extend(_render_pattern(p) for p in positives)

    negatives = sorted(
        (p for p in PATTERN_REGISTRY.values() if p.polarity == "negative"),
        key=lambda p: p.id,
    )
    sections.append(_KNOWLEDGE_PACK_HEADER_NEGATIVES)
    sections.extend(_render_pattern(p) for p in negatives)

    referenced_qids: set[str] = {
        qid
        for pattern in PATTERN_REGISTRY.values()
        for qid in pattern.question_template_ids
    }
    referenced_templates = sorted(
        (QUESTION_CATALOG[qid] for qid in referenced_qids if qid in QUESTION_CATALOG),
        key=lambda template: template.id,
    )
    sections.append(_KNOWLEDGE_PACK_HEADER_QUESTIONS)
    sections.extend(
        _render_question_template(template) for template in referenced_templates
    )

    return "\n\n".join(sections) + "\n"
