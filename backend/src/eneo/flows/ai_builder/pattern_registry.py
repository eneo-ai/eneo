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
  `"negative"` archetypes are anti-patterns grounded in FCM truth.

`PATTERN_REGISTRY_VERSION` is the monotonic integer persisted alongside
plans and digests. Any pattern-surface change bumps it by one alongside
a fingerprint update, mirroring the FCM bump-discipline policy.

The module also owns the tiny chain-step vocabulary used by patterns. Pattern
objects store backend tokens; `render_chain_shape` translates those tokens into
prompt-safe labels. Concrete compiler step text lives with the compiler.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

PATTERN_REGISTRY_VERSION: int = 9

PatternId = str
ChainStepToken = str
FLOW_INPUT_AUDIO_TRANSCRIPTION = "flow_input_audio_transcription"
FLOW_INPUT_DOCUMENT_UPLOAD = "flow_input_document_upload"
FLOW_INPUT_SECTIONED_FORM_FIELDS = "flow_input_sectioned_form_fields"
EXTRACT_TEMPLATE_VARIABLES_STEP = "extract_template_variables_step"
COMPOSE_SECTIONS_STEP = "compose_sections_step"
TEMPLATE_FILL_DOCX_STEP = "template_fill_docx_step"
TERMINAL_ARTIFACT_STEP = "terminal_artifact_step"

PatternPolarity = Literal["positive", "negative"]
PatternChainKind = Literal["none", "compiled", "planner_only"]
_VALID_POLARITIES: frozenset[str] = frozenset({"positive", "negative"})
_VALID_CHAIN_KINDS: frozenset[str] = frozenset({"none", "compiled", "planner_only"})


@dataclass(frozen=True, slots=True)
class ChainStepDescriptor:
    """Developer-owned metadata for backend pattern-chain tokens.

    Pattern chains are server/compiler vocabulary. The LLM should see a
    readable shape, not these token names, so every token used by the Pattern
    Registry must have human-readable metadata here.
    """

    token: str
    label: str


CHAIN_STEP_DESCRIPTORS: Mapping[str, ChainStepDescriptor] = MappingProxyType(
    {
        FLOW_INPUT_AUDIO_TRANSCRIPTION: ChainStepDescriptor(
            token=FLOW_INPUT_AUDIO_TRANSCRIPTION,
            label="transcribe uploaded audio",
        ),
        FLOW_INPUT_DOCUMENT_UPLOAD: ChainStepDescriptor(
            token=FLOW_INPUT_DOCUMENT_UPLOAD,
            label="receive uploaded document material",
        ),
        FLOW_INPUT_SECTIONED_FORM_FIELDS: ChainStepDescriptor(
            token=FLOW_INPUT_SECTIONED_FORM_FIELDS,
            label="collect runtime input fields",
        ),
        EXTRACT_TEMPLATE_VARIABLES_STEP: ChainStepDescriptor(
            token=EXTRACT_TEMPLATE_VARIABLES_STEP,
            label="extract template variables",
        ),
        COMPOSE_SECTIONS_STEP: ChainStepDescriptor(
            token=COMPOSE_SECTIONS_STEP,
            label="compose sections",
        ),
        TEMPLATE_FILL_DOCX_STEP: ChainStepDescriptor(
            token=TEMPLATE_FILL_DOCX_STEP,
            label="fill DOCX template",
        ),
        TERMINAL_ARTIFACT_STEP: ChainStepDescriptor(
            token=TERMINAL_ARTIFACT_STEP,
            label="create final output",
        ),
    }
)


def render_chain_shape(chain_steps: tuple[str, ...]) -> str:
    """Render backend chain tokens as prompt-safe semantic guidance."""

    return " -> ".join(
        CHAIN_STEP_DESCRIPTORS[chain_step].label for chain_step in chain_steps
    )


@dataclass(frozen=True, slots=True)
class Pattern:
    """Structural planner-strategy archetype.

    Frozen + slotted: the registry is canonical; patterns must not be
    mutated after construction.

    Fields are structural only. No labels, descriptions, help text, or
    localized copy — those belong to the Question Catalog and product
    surfaces that render patterns to users.

    `chain_steps` is the backend/compiler token sequence for patterns whose
    canonical realisation is multi-step. Knowledge-pack rendering translates
    these tokens into human-readable `chain_shape` guidance; raw tokens are
    not part of the LLM contract. Single-step shapes leave it empty.

    The registry deliberately avoids prompt recipe coupling. Patterns
    describe structural intent; the backend compiler and Flow capability
    manifest decide mechanics.
    """

    id: PatternId
    examples: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    negative_examples: tuple[str, ...]
    required_architectural_slots: tuple[str, ...]
    question_template_ids: tuple[str, ...]
    polarity: PatternPolarity
    chain_steps: tuple[str, ...] = ()
    chain_kind: PatternChainKind = "none"

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Pattern id must be a non-empty string")
        if self.polarity not in _VALID_POLARITIES:
            raise ValueError(
                f"Pattern polarity must be one of "
                f"{sorted(_VALID_POLARITIES)}; got {self.polarity!r}"
            )
        if self.chain_kind not in _VALID_CHAIN_KINDS:
            raise ValueError(
                f"Pattern chain_kind must be one of "
                f"{sorted(_VALID_CHAIN_KINDS)}; got {self.chain_kind!r}"
            )
        if self.chain_steps and self.chain_kind == "none":
            raise ValueError("Patterns with chain_steps must set chain_kind.")
        if not self.chain_steps and self.chain_kind != "none":
            raise ValueError("Patterns without chain_steps must use chain_kind='none'.")


def _pattern(
    *,
    id: PatternId,
    examples: tuple[str, ...],
    retrieval_hints: tuple[str, ...],
    required_architectural_slots: tuple[str, ...],
    question_template_ids: tuple[str, ...] = (),
    negative_examples: tuple[str, ...] = (),
    polarity: PatternPolarity = "positive",
    chain_steps: tuple[str, ...] = (),
    chain_kind: PatternChainKind = "none",
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
        chain_kind=chain_kind,
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
    ),
    _pattern(
        id="json_to_structured_payload",
        examples=(
            "JSON in, JSON out transformation",
            "normalize or enrich a runtime JSON payload",
        ),
        retrieval_hints=(
            "json payload transform normalize map schema",
            "input_type=json output_type=json output_mode=pass_through",
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
        id="json_to_text_summary",
        examples=(
            "JSON in, readable text out",
            "summarize a runtime JSON payload for a human reader",
        ),
        retrieval_hints=(
            "json payload summarize readable text",
            "input_type=json output_type=text output_mode=pass_through",
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
        id="json_to_artifact_report",
        examples=(
            "JSON in, generated PDF or DOCX report out",
            "turn a runtime JSON payload into a document artifact",
        ),
        retrieval_hints=(
            "json payload report artifact pdf docx",
            "input_type=json output_type=pdf docx output_mode=pass_through",
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
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
        chain_kind="compiled",
    ),
    _pattern(
        id="document_to_pdf_report",
        examples=(
            "document in, PDF out via generation",
            "PDF report synthesized from document inputs",
        ),
        retrieval_hints=(
            "pdf report generate document",
            "output_type=pdf output_mode=render_verbatim",
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
    ),
    _pattern(
        id="audio_to_artifact_report",
        examples=(
            "audio in, generated report artifact out",
            "transcribe audio and produce PDF, DOCX, JSON, or structured text",
        ),
        retrieval_hints=(
            "audio transcribe summarize report artifact",
            "input_type=audio output_type=pdf docx json text",
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
            FLOW_INPUT_AUDIO_TRANSCRIPTION,
            TERMINAL_ARTIFACT_STEP,
        ),
        chain_kind="compiled",
    ),
    _pattern(
        id="text_to_artifact_report",
        examples=(
            "text in, generated report artifact out",
            "turn pasted or transcribed text into a PDF or DOCX report",
        ),
        retrieval_hints=(
            "text report artifact pdf docx generated",
            "input_type=text output_type=pdf docx output_mode=render_verbatim",
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
            FLOW_INPUT_SECTIONED_FORM_FIELDS,
            COMPOSE_SECTIONS_STEP,
        ),
        chain_kind="planner_only",
    ),
    # General-purpose counterpart to `sectioned_form_intake`. Matches any
    # flow shape where the user supplies one or more named runtime
    # variables alongside the primary input — e.g. "name + role +
    # description", "language + focus", "reference id + owning unit". The
    # sectioned variant stays for the narrower rubric-per-field shape.
    # Form-field realization is backend-compiled from semantic runtime
    # input-field intent, not from prompt recipe selection.
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
            "runtime_metadata_fields",
        ),
        question_template_ids=(
            "primary_runtime_input",
            "terminal_output",
            "runtime_metadata_fields",
        ),
    ),
    _pattern(
        id="mcp_tool_step",
        examples=(
            "step uses a specific MCP tool for live external data",
            "external system action isolated to one step with tool-level MCP refs",
        ),
        retrieval_hints=(
            "mcp mcp_tool_refs mcp_server_refs",
            "external_system live_data integration_endpoint",
            "least_privilege step_scoped_tool_access",
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
    # Canonical multi-source fan-in shape: one source step feeds two or
    # more parallel JSON extractions, then a single text step composes
    # from all of them via `uses_previous_fields`. Without this archetype
    # the planner tends to chain extractions through `previous_step` and
    # the composer ends up reading only the immediate prior, silently
    # losing the earlier extractions.
    _pattern(
        id="source_parallel_extractions_to_final_text",
        examples=(
            "single source feeds multiple parallel JSON extractions, "
            "then a final text step composes from all of them",
            "audio or document upload → several JSON extractions in "
            "parallel → composed text summary that references each "
            "extraction's structured fields",
        ),
        retrieval_hints=(
            "parallel multi-aspect extraction fan-in composition",
            "extrahera flera olika perspektiv aspekter dimensioner",
            "för varje rubrik kategori per ämne",
            "uses_previous_fields previous_step refs across multiple JSON priors",
            "input_type=text|audio|document output_type=json output_type=text",
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

COMPILED_CHAIN_PATTERN_IDS: frozenset[str] = frozenset(
    pattern.id
    for pattern in PATTERN_REGISTRY.values()
    if pattern.chain_kind == "compiled"
)
PLANNER_ONLY_CHAIN_PATTERN_IDS: frozenset[str] = frozenset(
    pattern.id
    for pattern in PATTERN_REGISTRY.values()
    if pattern.chain_kind == "planner_only"
)


def compiled_chain_pattern_ids(pattern_ids: Iterable[str]) -> frozenset[str]:
    """Return selected pattern ids whose chains are backend-compiled.

    Multiple planner patterns can be committed together, but compiler-backed
    chain patterns are currently wrappers, not freely composable transforms.
    Architecture validation uses this helper to reject ambiguous commits
    before a plan can silently drop one chain.
    """

    return frozenset(
        pattern_id
        for pattern_id in pattern_ids
        if pattern_id in COMPILED_CHAIN_PATTERN_IDS
    )


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
