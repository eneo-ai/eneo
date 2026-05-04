"""Conversation-spec alignment invariants consulted by the quality critic.

Each `CriticInvariant` is a self-contained rule with an id, kind, evidence
predicate, and remediation. Semantic invariants are repairable planner feedback;
architecture invariants are backend-owned mechanics failures.

`CRITIC_INVARIANTS` is the single public registry; its registration order
pins the order planner-visible issues surface in. Callers that need a
narrower view can filter the tuple inline and pass `invariants=` to
`render_critic_issues`.

Layering: this module imports AI Builder types (`FlowDraftSpecCore`,
`OutputIntentResolution`, `PlannerPatternSignals`) and form-intake signals.
The Flow Capability Manifest stays engine-truth-only and does not learn
about conversation signals; those live here with the rest of the AI Builder
layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_form_field_usage import (
    find_unused_form_fields,
)
from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_sectioned_form_intake,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    needs_structured_extraction,
    runtime_metadata_requested,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    PrimaryRuntimeInput,
    degrades_document_entry_to_generic_file,
    has_real_audio_transcription_step,
    uses_pseudo_transcription_without_audio_step,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    find_named_mcp_reference_issue,
)
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    PlannerPatternSignals,
)
from intric.flows.ai_builder.planning_state import AggregationIntent
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_resource_catalog import (
        AIBuilderResourceCatalog,
    )
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class CriticContext:
    """Pre-computed view of conversation + spec + flow used by every invariant.

    The critic builds the context once per call, then hands it to each
    `CriticInvariant.evidence` — invariants never re-parse the raw
    conversation. Any value computed more than once across the invariant
    loop belongs here.
    """

    spec: FlowDraftSpecCore
    flow: "Flow | None"
    answer_signals: dict[str, set[str]]
    text: str
    requirements_text: str
    signal_text: str
    planner_patterns: PlannerPatternSignals
    output_intent: OutputIntentResolution
    mixed_audio_doc_input: bool
    primary_runtime_input: PrimaryRuntimeInput = "unknown"
    aggregation_intent: AggregationIntent = "linear"
    resource_catalog: "AIBuilderResourceCatalog | None" = None


CriticCheck = Callable[[CriticContext], bool]
CriticInvariantKind = Literal["architecture", "semantic"]


@dataclass(frozen=True, slots=True)
class CriticIssue:
    id: str
    kind: CriticInvariantKind
    remediation: str


@dataclass(frozen=True, slots=True)
class CriticInvariant:
    """Conversation-spec alignment invariant.

    `evidence(context)` returns True when the invariant is violated and the
    critic should surface `remediation` to the planner.
    """

    id: str
    kind: CriticInvariantKind
    description: str
    evidence: CriticCheck
    remediation: str


# ── Shared helpers ───────────────────────────────────────────────────────

# Markers for the user explicitly asking for structured JSON extraction for
# downstream reuse — not any incidental mention of "json".
_JSON_CONTRACT_MARKERS: tuple[str, ...] = (
    "json",
    "strukturerad data",
    "structured data",
    "extract fields",
    "extrahera fält",
    "output contract",
    "output_contract",
)

# Markers for a human-readable terminal result (summary, report, analysis) —
# output_type=text is appropriate there; no JSON warning.
_HUMAN_READABLE_TERMINAL_MARKERS: tuple[str, ...] = (
    "sammanfatt",
    "summarize",
    "summary",
    "rapport",
    "report",
    "analys",
    "analysis",
    "beslut",
    "decision",
    "overview",
    "överblick",
    "skriv",
    "write",
)

_DOWNSTREAM_REUSE_MARKERS: tuple[str, ...] = (
    "downstream",
    "vidare",
    "reuse",
    "återanvänd",
    "next step",
    "nästa steg",
)

_FIELD_REUSE_MARKERS: tuple[str, ...] = (
    "specific fields",
    "specific json fields",
    "use the fields",
    "använd fälten",
    "specifika fälten",
    "namngivna fält",
    "key clauses",
    "nyckelfakta",
)


def has_json_contract_step(spec: FlowDraftSpecCore) -> bool:
    """True when the spec has a non-terminal JSON step with an output contract.

    A single-step spec whose only step is JSON does not count — without a
    downstream consumer the contract provides no value.
    """
    for index, step in enumerate(spec.steps):
        if step.output_type != OutputType.JSON:
            continue
        if step.output_contract is None:
            continue
        if index == len(spec.steps) - 1 and len(spec.steps) == 1:
            continue
        return True
    return False


def _spec_uses_template_fill(spec: FlowDraftSpecCore) -> bool:
    return any(step.output_mode == OutputMode.TEMPLATE_FILL for step in spec.steps)


def _conversation_requests_json_contract(text: str) -> bool:
    return any(marker in text for marker in _JSON_CONTRACT_MARKERS)


def _terminal_step_is_human_readable_only(text: str, spec: FlowDraftSpecCore) -> bool:
    """True when the final step is clearly meant to produce human-readable
    output and the conversation does not mention downstream reuse.

    Used by the anti-over-structuring guardrail — suppresses the JSON warning
    when the user simply wants a summary/report/analysis.
    """
    if not spec.steps:
        return False
    terminal = spec.steps[-1]
    if terminal.output_type not in {OutputType.TEXT, OutputType.DOCX, OutputType.PDF}:
        return False
    if any(marker in text for marker in _DOWNSTREAM_REUSE_MARKERS):
        return False
    return any(marker in text for marker in _HUMAN_READABLE_TERMINAL_MARKERS)


def _spec_handles_audio(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_type == InputType.AUDIO
        or step.output_mode == OutputMode.TRANSCRIBE_ONLY
        for step in spec.steps
    )


def _conversation_requests_field_reuse(text: str) -> bool:
    return any(marker in text for marker in _FIELD_REUSE_MARKERS)


def _spec_uses_input_bindings(spec: FlowDraftSpecCore) -> bool:
    return any(step.input_bindings for step in spec.steps)


def _spec_uses_all_previous_steps(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source == InputSource.ALL_PREVIOUS_STEPS for step in spec.steps
    )


def _mcp_selection_lacks_semantic_support(context: CriticContext) -> bool:
    catalog = context.resource_catalog
    if catalog is None:
        return False
    return (
        find_named_mcp_reference_issue(
            spec=context.spec,
            catalog=catalog,
            signal_text=context.signal_text,
        )
        is not None
    )


def _is_output_only_edit(context: CriticContext) -> bool:
    """True when the edit looks like a pure final-format change.

    Requires: a flow anchor, a preserved step count ≥ 2, an explicit
    terminal-output intent, and a terminal-output change between the
    original and planned final steps.
    """
    flow = context.flow
    explicit_output = context.output_intent.terminal_output
    spec = context.spec
    if flow is None or explicit_output not in {"pdf_document", "docx_document"}:
        return False

    original_steps = sorted(flow.steps, key=lambda step: step.step_order)
    if len(spec.steps) != len(original_steps) or len(spec.steps) < 2:
        return False

    original_terminal_output = original_steps[-1].output_type
    requested_terminal_output = "pdf" if explicit_output == "pdf_document" else "docx"
    return original_terminal_output != requested_terminal_output


def _non_terminal_steps_converted_to_document(context: CriticContext) -> bool:
    if not _is_output_only_edit(context):
        return False
    flow = context.flow
    assert flow is not None  # guarded by _is_output_only_edit
    original_steps = sorted(flow.steps, key=lambda step: step.step_order)
    for original_step, planned_step in zip(
        original_steps[:-1], context.spec.steps[:-1], strict=False
    ):
        original_is_document_output = original_step.output_type in {"pdf", "docx"}
        planned_is_document_output = planned_step.output_type in {
            OutputType.PDF,
            OutputType.DOCX,
        }
        if not original_is_document_output and planned_is_document_output:
            return True
    return False


def _non_terminal_steps_adopt_template_fill(context: CriticContext) -> bool:
    if not _is_output_only_edit(context):
        return False
    return any(
        step.output_mode == OutputMode.TEMPLATE_FILL for step in context.spec.steps[:-1]
    )


# ── Form-fields invariants ───────────────────────────────────────────────


def _runtime_metadata_requires_form_fields_evidence(context: CriticContext) -> bool:
    return (
        runtime_metadata_requested(context.answer_signals)
        and not context.spec.form_fields
    )


_RUNTIME_METADATA_REQUIRES_FORM_FIELDS = CriticInvariant(
    id="runtime_metadata_requires_form_fields",
    kind="semantic",
    description=(
        "When the user asked for reusable runtime metadata, the plan must model "
        "those values as `form_fields` instead of hiding them in prompt text."
    ),
    evidence=_runtime_metadata_requires_form_fields_evidence,
    remediation=(
        "Användaren har bett om återanvändbara metadata vid körning men planen saknar "
        "`form_fields`. Lägg till relevanta formulärfält i stället för att gömma dessa värden i prompttext."
    ),
)


def _sectioned_form_intake_requires_form_fields_evidence(
    context: CriticContext,
) -> bool:
    return mentions_sectioned_form_intake(context.text) and not context.spec.form_fields


_SECTIONED_FORM_INTAKE_REQUIRES_FORM_FIELDS = CriticInvariant(
    id="sectioned_form_intake_requires_form_fields",
    kind="semantic",
    description=(
        "Sectioned free-text intake (one rubric/section per field) must be "
        "modelled as `form_fields`, not as a per-section collection step."
    ),
    evidence=_sectioned_form_intake_requires_form_fields_evidence,
    remediation=(
        "Konversationen beskriver sektionerad fritextinsamling per rubrik/sektion, men planen saknar "
        "`form_fields`. Modellera varje rubrik som ett eget textfält i `form_fields` i stället för att "
        "bygga ett separat insamlingssteg per sektion, och låt senare steg använda dessa fält via "
        "`uses_form_fields` för att skapa slutdokumentet."
    ),
)


def _rich_workflow_requires_form_fields_evidence(context: CriticContext) -> bool:
    patterns = context.planner_patterns
    return (
        patterns.rich_document_workflow
        and patterns.needs_form_fields
        and not patterns.derive_from_input_only
        and not context.spec.form_fields
    )


_RICH_WORKFLOW_REQUIRES_FORM_FIELDS = CriticInvariant(
    id="rich_workflow_requires_form_fields",
    kind="semantic",
    description=(
        "A rich document workflow that also needs manual completions must "
        "declare `form_fields` instead of hiding them in instruction text."
    ),
    evidence=_rich_workflow_requires_form_fields_evidence,
    remediation=(
        "Behovet beskriver ett dokumentbaserat flöde som också kräver manuella kompletteringar eller "
        "inmatningsfält, men planen saknar `form_fields`. Modellera dessa värden som form_fields i "
        "stället för att gömma dem i instruktionstexten."
    ),
)


def _rich_workflow_requires_json_contract_step_evidence(
    context: CriticContext,
) -> bool:
    patterns = context.planner_patterns
    return (
        patterns.rich_document_workflow
        and patterns.prefers_structured_intermediate
        and not has_json_contract_step(context.spec)
    )


_RICH_WORKFLOW_REQUIRES_JSON_CONTRACT_STEP = CriticInvariant(
    id="rich_workflow_requires_json_contract_step",
    kind="semantic",
    description=(
        "A rich document workflow that will reuse structured analysis must "
        "include an intermediate JSON step with an `output_contract`."
    ),
    evidence=_rich_workflow_requires_json_contract_step_evidence,
    remediation=(
        "Behovet beskriver ett dokumentflöde som ska återanvända strukturerad analys, men planen saknar "
        'ett tydligt JSON-steg med `output_contract`. Lägg till ett mellanliggande `output_type="json"`-steg '
        "innan slutlig rapport eller dokumentleverans."
    ),
)


def _rich_workflow_requires_multiple_steps_evidence(context: CriticContext) -> bool:
    patterns = context.planner_patterns
    return (
        patterns.rich_document_workflow
        and patterns.prefers_quality_step
        and len(context.spec.steps) < 3
    )


_RICH_WORKFLOW_REQUIRES_MULTIPLE_STEPS = CriticInvariant(
    id="rich_workflow_requires_multiple_steps",
    kind="semantic",
    description=(
        "A rich document workflow that calls for analysis or review must not "
        "collapse into fewer than three steps."
    ),
    evidence=_rich_workflow_requires_multiple_steps_evidence,
    remediation=(
        "Behovet beskriver ett mer genomarbetat dokumentflöde med analys, granskning eller kvalitetssäkring, "
        "men planen kollapsar fortfarande till för få steg. Lägg till minst ett mellanliggande analys- eller "
        "granskningssteg innan slutleveransen."
    ),
)


# ── Terminal-output alignment ────────────────────────────────────────────


def _pdf_terminal_alignment_evidence(context: CriticContext) -> bool:
    if context.output_intent.terminal_output != "pdf_document":
        return False
    if not context.spec.steps:
        return False
    return context.spec.steps[-1].output_type != OutputType.PDF


_PDF_TERMINAL_OUTPUT_ALIGNMENT = CriticInvariant(
    id="pdf_terminal_output_alignment",
    kind="architecture",
    description=(
        "When the user explicitly picks PDF as the final artefact, the terminal "
        "step must produce `output_type=PDF`."
    ),
    evidence=_pdf_terminal_alignment_evidence,
    remediation=(
        "Användaren har valt PDF som slutartefakt men sista steget producerar inte PDF. "
        "Justera slutstegets output_type så att det matchar användarens val."
    ),
)


def _docx_terminal_alignment_evidence(context: CriticContext) -> bool:
    if context.output_intent.terminal_output != "docx_document":
        return False
    if not context.spec.steps:
        return False
    return context.spec.steps[-1].output_type != OutputType.DOCX


_DOCX_TERMINAL_OUTPUT_ALIGNMENT = CriticInvariant(
    id="docx_terminal_output_alignment",
    kind="architecture",
    description=(
        "When the user explicitly picks DOCX as the final artefact, the "
        "terminal step must produce `output_type=DOCX`."
    ),
    evidence=_docx_terminal_alignment_evidence,
    remediation=(
        "Användaren har valt DOCX som slutartefakt men sista steget producerar inte DOCX. "
        "Justera slutstegets output_type så att det matchar användarens val."
    ),
)


# ── Output-only edits (flow-anchored) ────────────────────────────────────


_NON_TERMINAL_STEP_DOCUMENT_CONVERSION_FORBIDDEN = CriticInvariant(
    id="non_terminal_step_document_conversion_forbidden",
    kind="architecture",
    description=(
        "When the user only asks to change the final artefact format, the "
        "plan must not flip intermediate analysis steps to DOCX/PDF output."
    ),
    evidence=_non_terminal_steps_converted_to_document,
    remediation=(
        "Användaren verkar bara vilja ändra slutformatet men planen har bytt mellanliggande analyssteg "
        "till dokumentutdata (DOCX/PDF). Håll upstream-stegen som text/json-analyssteg och lägg "
        "dokumentgenereringen enbart på slutsteget."
    ),
)


_NON_TERMINAL_STEP_TEMPLATE_FILL_FORBIDDEN = CriticInvariant(
    id="non_terminal_step_template_fill_forbidden",
    kind="architecture",
    description=(
        "`output_mode=template_fill` only makes sense on the terminal step of "
        "an output-format edit; intermediate steps must stay analytical."
    ),
    evidence=_non_terminal_steps_adopt_template_fill,
    remediation=(
        "Användaren verkar bara vilja ändra slutformatet men planen använder `template_fill` på "
        "mellanliggande steg. Begränsa `template_fill` till slutsteget och låt mellanliggande steg "
        "förbli analyssteg."
    ),
)


# ── Structured extraction / JSON contract ────────────────────────────────


def _structured_extraction_requires_json_contract_step_evidence(
    context: CriticContext,
) -> bool:
    spec = context.spec
    if not spec.steps:
        return False
    return needs_structured_extraction(
        context.text,
        context.answer_signals,
        step_count=len(spec.steps),
        terminal_output_type=spec.steps[-1].output_type,
    ) and not has_json_contract_step(spec)


_STRUCTURED_EXTRACTION_REQUIRES_JSON_CONTRACT_STEP = CriticInvariant(
    id="structured_extraction_requires_json_contract_step",
    kind="semantic",
    description=(
        "Conversations that imply downstream reuse of structured fields must "
        "include a JSON contract step before the terminal output."
    ),
    evidence=_structured_extraction_requires_json_contract_step_evidence,
    remediation=(
        "Planen verkar behöva strukturerad extraktion för vidare återanvändning, men saknar ett "
        '`output_type="json"`-steg med `output_contract`. Lägg till ett tydligt JSON-extraktionssteg '
        "innan den slutliga text- eller dokumentproduktionen."
    ),
)


def _explicit_json_contract_request_without_step_evidence(
    context: CriticContext,
) -> bool:
    """Fire only when the user explicitly asks for structured JSON extraction
    for downstream reuse — never for simple human-readable terminal output.
    """
    text = context.text
    spec = context.spec
    if not _conversation_requests_json_contract(text):
        return False
    if has_json_contract_step(spec):
        return False
    return not _terminal_step_is_human_readable_only(text, spec)


_EXPLICIT_JSON_CONTRACT_REQUEST_WITHOUT_STEP = CriticInvariant(
    id="explicit_json_contract_request_without_step",
    kind="semantic",
    description=(
        "When the conversation explicitly asks for JSON/fields/contracts, the "
        "plan must include a JSON-extraction step unless the terminal step is "
        "plainly human-readable."
    ),
    evidence=_explicit_json_contract_request_without_step_evidence,
    remediation=(
        "Konversationen nämner strukturerad extraktion (JSON, fält, kontrakt) men inget steg "
        'använder `output_type="json"` med `output_contract`. Lägg till ett JSON-extraktionssteg '
        "om data ska återanvändas i nästa steg eller av ett externt system."
    ),
)


# ── Standalone audio ─────────────────────────────────────────────────────


def _standalone_audio_requires_transcription_step_evidence(
    context: CriticContext,
) -> bool:
    if context.primary_runtime_input != "audio":
        return False
    if _spec_handles_audio(context.spec):
        return False
    return not context.mixed_audio_doc_input


_STANDALONE_AUDIO_REQUIRES_TRANSCRIPTION_STEP = CriticInvariant(
    id="standalone_audio_requires_transcription_step",
    kind="architecture",
    description=(
        "When the slot classifier resolves the runtime input to audio (not "
        "mixed with documents), the plan must include a dedicated "
        "transcription step."
    ),
    evidence=_standalone_audio_requires_transcription_step_evidence,
    remediation=(
        "Inmatningen är ljud men inget steg transkriberar ljud till text. "
        "Lägg till ett dedikerat transkriberingssteg som första steg i flödet med:\n"
        '  - `input_type: "audio"`\n'
        '  - `input_source: "flow_input"`\n'
        '  - `output_type: "text"`\n'
        '  - `output_mode: "transcribe_only"`\n'
        "Efterföljande steg läser transkriptet via "
        '`input_source="previous_step"` och `input_type="text"`. Om planen redan '
        "har flera steg, skjut dem ett steg framåt och lägg transkriberingssteget "
        "vid position 0."
    ),
)


# ── Field reuse across JSON steps ────────────────────────────────────────


def _field_reuse_requires_input_bindings_evidence(context: CriticContext) -> bool:
    return (
        _conversation_requests_field_reuse(context.text)
        and has_json_contract_step(context.spec)
        and not _spec_uses_input_bindings(context.spec)
    )


_FIELD_REUSE_REQUIRES_INPUT_BINDINGS = CriticInvariant(
    id="field_reuse_requires_input_bindings",
    kind="semantic",
    description=(
        "When the conversation reuses named JSON fields downstream, the plan "
        "must declare `input_bindings` / `uses_previous_fields`."
    ),
    evidence=_field_reuse_requires_input_bindings_evidence,
    remediation=(
        "Konversationen antyder återanvändning av specifika fält från strukturerad extraktion, men planen saknar "
        "`uses_previous_fields` i efterföljande steg. Deklarera explicita JSON-fält vidare när nästa steg behöver utvalda datapunkter."
    ),
)


# ── Multi-document compare ───────────────────────────────────────────────


def _multi_document_compare_requires_all_previous_steps_evidence(
    context: CriticContext,
) -> bool:
    return (
        context.aggregation_intent in {"aggregate", "compare"}
        and _spec_has_multiple_content_steps(context.spec)
        and not _spec_uses_all_previous_steps(context.spec)
    )


def _is_renderer_step(step: StepSpec) -> bool:
    """True for template-fill / DOCX / PDF stubs — document assembly steps
    the backend wires, not compositional content steps a stitch step would
    reference by field path."""
    return step.output_mode == OutputMode.TEMPLATE_FILL or step.output_type in {
        OutputType.DOCX,
        OutputType.PDF,
    }


def _spec_has_multiple_content_steps(spec: FlowDraftSpecCore) -> bool:
    content_steps = [step for step in spec.steps if not _is_renderer_step(step)]
    return len(content_steps) >= 2


_MULTI_DOCUMENT_COMPARE_REQUIRES_ALL_PREVIOUS_STEPS = CriticInvariant(
    id="multi_document_compare_requires_all_previous_steps",
    kind="architecture",
    description=(
        "When the conversation describes comparing or aggregating multiple "
        "documents, at least one step must use "
        "`input_source=all_previous_steps`."
    ),
    evidence=_multi_document_compare_requires_all_previous_steps_evidence,
    remediation=(
        "Konversationen beskriver jämförelse eller samlad analys av flera dokument, men inget steg använder "
        '`input_source="all_previous_steps"`. Använd en aggregerande eller jämförande koppling när flera dokument ska behandlas tillsammans.'
    ),
)


# ── MCP resource alignment ───────────────────────────────────────────────


_MCP_SELECTION_REQUIRES_SEMANTIC_SUPPORT = CriticInvariant(
    id="mcp_selection_requires_semantic_support",
    kind="semantic",
    description=(
        "A step must not attach unrelated MCP resources just because the user "
        "mentioned MCP. Selected server/tool metadata must match the step "
        "intent; otherwise the planner should ask for clarification."
    ),
    evidence=_mcp_selection_lacks_semantic_support,
    remediation=(
        "Planen hänvisar till MCP på ett sätt som inte matchar tillgänglig metadata. "
        "Välj bara MCP-server eller MCP-verktyg när användarens namngivna MCP finns "
        "aktiverat i ytan och matchar samma server. Om MCP-valet är oklart eller saknas, "
        "fråga om förtydligande i stället för att ersätta det med ett annat MCP."
    ),
)


# ── JSON input rejects all_previous_steps source ────────────────────────


def _json_input_rejects_all_previous_steps_source_evidence(
    context: CriticContext,
) -> bool:
    return any(
        step.input_type == InputType.JSON
        and step.input_source == InputSource.ALL_PREVIOUS_STEPS
        for step in context.spec.steps
    )


_JSON_INPUT_REJECTS_ALL_PREVIOUS_STEPS_SOURCE = CriticInvariant(
    id="json_input_rejects_all_previous_steps_source",
    kind="architecture",
    description=(
        "A step declaring `input_type=json` cannot read from "
        "`input_source=all_previous_steps` because the runtime concatenates "
        "prior step output as text, which is not valid JSON."
    ),
    evidence=_json_input_rejects_all_previous_steps_source_evidence,
    remediation=(
        'Ett steg har `input_type="json"` tillsammans med `input_source="all_previous_steps"`, '
        "vilket inte kan köras eftersom sammanslagen text från tidigare steg inte är giltig JSON. "
        'Välj en av: (a) sätt `input_source="previous_step"` och hänvisa till specifika fält '
        "via `uses_previous_fields` när steget ska läsa strukturerad JSON från det omedelbart "
        'föregående steget; eller (b) sätt `input_type="text"` när steget ska sammanfatta '
        "eller syntetisera textinnehållet från alla tidigare steg."
    ),
)


# ── Targeted underlag preferred over all_previous_steps ─────────────────


TARGETED_UNDERLAG_SOFT_CAP = 6


def _last_compositional_step_index(spec: FlowDraftSpecCore) -> int | None:
    """Index of the last step that composes content.

    Document-output flows often end with a renderer (template_fill DOCX,
    raw DOCX/PDF) that the backend wires. The actual content composition
    happens one step earlier; the targeted-underlag rule must evaluate
    that step's input wiring, not the renderer's.
    """
    for index in range(len(spec.steps) - 1, -1, -1):
        if not _is_renderer_step(spec.steps[index]):
            return index
    return None


def _composer_question_targets_prior_structured_field(
    *, spec: FlowDraftSpecCore, composer_index: int
) -> bool:
    """True when the composer's `input_bindings.question` resolves to a
    structured field on a step that runs before it.

    Uses the canonical `analyze_template` parser so the predicate stays
    aligned with how the runtime actually resolves `{{ ... }}`
    expressions — including JSON-escaped quoting and arbitrarily deep
    `output.structured.<a>.<b>...` paths. Future or current-step
    references and parse errors do not count as targeted underlag.
    """
    composer = spec.steps[composer_index]
    if composer.input_bindings is None:
        return False
    question = composer.input_bindings.get("question")
    if not isinstance(question, str) or not question:
        return False
    step_refs = {step.plan_step_ref: index for index, step in enumerate(spec.steps)}
    form_field_names = {field.name for field in (spec.form_fields or [])}
    references = analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=form_field_names,
    )
    return any(
        reference.kind is TemplateReferenceKind.STEP
        and reference.path_error_code is None
        and reference.step_order is not None
        and reference.step_order < composer_index
        and reference.structured_path
        for reference in references
    )


def _prefer_targeted_underlag_over_all_previous_steps_evidence(
    context: CriticContext,
) -> bool:
    """Fire when the last compositional step reads
    `input_source=all_previous_steps` while ≥1 prior content step
    emits structured JSON the composer could reference selectively.

    Suppression cases:
    - aggregation_intent in {aggregate, compare}: the multi-document
      compare invariant already requires `all_previous_steps`.
    - >`TARGETED_UNDERLAG_SOFT_CAP` prior content steps: an explicit
      underlag template grows past the point where it is more legible
      than concatenation.
    - All priors are text-typed: there are no structured fields to
      reference — `all_previous_steps` is the only composition.
    - The composer's `input_bindings.question` already targets prior
      structured fields explicitly: the spec is effectively using
      targeted underlag despite the nominal source.
    """
    spec = context.spec
    if context.aggregation_intent in {"aggregate", "compare"}:
        return False
    if len(spec.steps) < 2:
        return False
    composer_index = _last_compositional_step_index(spec)
    if composer_index is None or composer_index == 0:
        return False
    composer = spec.steps[composer_index]
    if composer.input_source != InputSource.ALL_PREVIOUS_STEPS:
        return False
    if composer.input_type != InputType.TEXT:
        return False
    if _composer_question_targets_prior_structured_field(
        spec=spec, composer_index=composer_index
    ):
        return False
    priors = [
        step for step in spec.steps[:composer_index] if not _is_renderer_step(step)
    ]
    if not priors or len(priors) > TARGETED_UNDERLAG_SOFT_CAP:
        return False
    return any(
        step.output_type == OutputType.JSON and step.output_contract is not None
        for step in priors
    )


_PREFER_TARGETED_UNDERLAG_OVER_ALL_PREVIOUS_STEPS = CriticInvariant(
    id="prefer_targeted_underlag_over_all_previous_steps",
    kind="semantic",
    description=(
        "When the last compositional text step reads `all_previous_steps` "
        "but at least one prior content step emits a structured JSON "
        "output_contract, the spec should switch to `previous_step` and "
        "compose its underlag from explicit `uses_previous_fields` "
        "references. `all_previous_steps` concatenates every prior body "
        "text, scaling tokens monotonically with step count; targeted "
        "underlag scopes input to the fields the composer actually "
        "consumes. Document renderer terminals (template_fill, DOCX, PDF) "
        "are skipped — the rule evaluates the step that builds the body."
    ),
    evidence=_prefer_targeted_underlag_over_all_previous_steps_evidence,
    remediation=(
        'Det sista komponerande textsteget har `input_source="all_previous_steps"` '
        "fastän tidigare steg producerar strukturerad JSON. Det betyder att hela "
        "texten från alla tidigare steg sammanfogas och skickas in — token-kostnaden "
        "växer linjärt med antalet steg, även om det komponerande steget egentligen "
        "bara behöver några specifika fält. Byt till "
        '`input_source="previous_step"` och bygg underlaget explicit: deklarera '
        "`uses_previous_fields` för de fält som steget faktiskt läser och referera "
        "dem i `input_bindings.question` via `{{ step_<ref>.output.structured.<fält> }}`. "
        "Eventuella DOCX/PDF-renderingar i slutet förblir orörda — regeln gäller bara "
        "det komponerande textsteget."
    ),
)


def _composer_question_distinct_prior_structured_step_count(
    *, spec: FlowDraftSpecCore, composer_index: int
) -> int:
    """Number of distinct prior steps the composer's `input_bindings.question`
    pulls a structured field from.

    Mirrors `_composer_question_targets_prior_structured_field` but counts
    distinct prior step indices rather than collapsing to a boolean. Used
    by the under-bind rule, which suppresses only when ≥2 priors are
    already targeted (one prior is the auto-binder's bare-minimum case
    and still leaves earlier predecessors silently dropped).
    """
    composer = spec.steps[composer_index]
    if composer.input_bindings is None:
        return 0
    question = composer.input_bindings.get("question")
    if not isinstance(question, str) or not question:
        return 0
    step_refs = {step.plan_step_ref: index for index, step in enumerate(spec.steps)}
    form_field_names = {field.name for field in (spec.form_fields or [])}
    references = analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=form_field_names,
    )
    distinct: set[int] = set()
    for reference in references:
        if reference.kind is not TemplateReferenceKind.STEP:
            continue
        if reference.path_error_code is not None:
            continue
        if reference.step_order is None or reference.step_order >= composer_index:
            continue
        if not reference.structured_path:
            continue
        distinct.add(reference.step_order)
    return len(distinct)


def _final_text_step_must_reference_relevant_structured_outputs_evidence(
    context: CriticContext,
) -> bool:
    """Fire when the last compositional text step reads `previous_step`
    but at least two prior content steps emit structured JSON the
    composer is silently dropping.

    Defense-in-depth complement of
    `prefer_targeted_underlag_over_all_previous_steps`. The over-fan
    shape (`all_previous_steps` with structured priors) is owned by
    that rule; this rule covers the opposite under-bind shape where the
    composer reads `previous_step` and only sees the most recent JSON
    predecessor — even though earlier predecessors carry distinct
    fields the composer almost certainly needs.

    Suppression cases mirror `prefer_targeted_underlag`:
    - aggregation_intent in {aggregate, compare}: those flows go
      through the multi-document compare invariant.
    - >`TARGETED_UNDERLAG_SOFT_CAP` prior content steps: an explicit
      underlag template stops being more legible than concatenation.
    - <2 prior content steps emit JSON+output_contract: there is no
      fan-in to surface, only a 2-step refinement chain.
    - The composer's `input_bindings.question` already targets ≥2
      distinct prior structured fields: the spec is doing what the
      rule would suggest despite the nominal source shape.
    """
    spec = context.spec
    if context.aggregation_intent in {"aggregate", "compare"}:
        return False
    if len(spec.steps) < 2:
        return False
    composer_index = _last_compositional_step_index(spec)
    if composer_index is None or composer_index == 0:
        return False
    composer = spec.steps[composer_index]
    if composer.input_source != InputSource.PREVIOUS_STEP:
        return False
    if composer.output_type != OutputType.TEXT:
        return False
    priors = [
        step for step in spec.steps[:composer_index] if not _is_renderer_step(step)
    ]
    if len(priors) > TARGETED_UNDERLAG_SOFT_CAP:
        return False
    json_priors = [
        step
        for step in priors
        if step.output_type == OutputType.JSON and step.output_contract is not None
    ]
    if len(json_priors) < 2:
        return False
    if (
        _composer_question_distinct_prior_structured_step_count(
            spec=spec, composer_index=composer_index
        )
        >= 2
    ):
        return False
    return True


_FINAL_TEXT_STEP_MUST_REFERENCE_RELEVANT_STRUCTURED_OUTPUTS = CriticInvariant(
    id="final_text_step_must_reference_relevant_structured_outputs",
    kind="semantic",
    description=(
        "When the last compositional text step reads `previous_step` and "
        "at least two prior content steps emit a structured JSON "
        "output_contract, the composer must reference structured fields "
        "from at least two of those priors via `uses_previous_fields` and "
        "explicit `{{ step_<ref>.output.structured.<field> }}` selectors "
        "in `input_bindings.question`. A `previous_step` composer that "
        "only sees the immediate predecessor silently drops the fields "
        "earlier predecessors emit. Document renderer terminals are "
        "skipped — the rule evaluates the step that builds the body."
    ),
    evidence=_final_text_step_must_reference_relevant_structured_outputs_evidence,
    remediation=(
        'Det sista komponerande textsteget läser `input_source="previous_step"` '
        "fastän flera tidigare steg producerar strukturerad JSON. Det betyder att "
        "endast det omedelbart föregående steget syns för komponenten — fält från "
        "ännu tidigare steg går förlorade. Behåll "
        '`input_source="previous_step"` men deklarera `uses_previous_fields` för '
        "de fält som steget faktiskt behöver från varje relevant tidigare steg "
        "och referera dem i `input_bindings.question` via "
        "`{{ step_<ref>.output.structured.<fält> }}`. Eventuella DOCX/PDF-renderingar "
        "i slutet förblir orörda — regeln gäller bara det komponerande textsteget."
    ),
)


def _form_fields_declared_must_be_referenced_evidence(
    context: CriticContext,
) -> bool:
    """Fire when the spec declares form_fields no step references.

    A declared but unreferenced form_field reaches the user as an
    input control with no effect on flow behaviour. The runtime would
    silently inject the value into a step that never consumes it,
    polluting the prompt context. The planner gets a repair turn so it
    can either remove the field or wire it through a step's templates.
    """
    return bool(find_unused_form_fields(context.spec))


_FORM_FIELDS_DECLARED_MUST_BE_REFERENCED = CriticInvariant(
    id="form_fields_declared_must_be_referenced",
    kind="semantic",
    description=(
        "Every form_field declared on the flow must be referenced by at "
        "least one step's templates (instructions, input_bindings, or "
        "output_config). Unreferenced fields surface as live UI controls "
        "with no flow behaviour and risk polluting downstream prompts at "
        "runtime."
    ),
    evidence=_form_fields_declared_must_be_referenced_evidence,
    remediation=(
        "Ett eller flera deklarerade fält saknar koppling till något steg. "
        "Reparera på något av följande sätt: "
        "(a) Skapa-läge: lista varje fält i `uses_input_fields` på minst ett "
        "steg som behöver värdet — kompilatorn injicerar då `{{ <namn> }}` "
        "automatiskt i stegets underlag/`input_bindings`. Skriv inte själva "
        "`{{ ... }}`-syntaxen i `task`-fältet (det är förbjudet av schemat). "
        "(b) Redigera-läge: lägg fältet i `uses_form_fields` på minst ett steg "
        "och referera det med exakt `{{ <namn> }}` (utan `form.`-prefix) i "
        "stegets `instructions` eller `input_bindings.question`. "
        "(c) Ta bort fältet helt om ingen ska läsa det. "
        "Fält som ingen läser visas som live-kontroller utan effekt på flödets "
        "beteende och riskerar att förorena nedströms prompts vid körning."
    ),
)


# ── DOCX output-mode alignment ───────────────────────────────────────────


def _template_fill_docx_requires_template_fill_step_evidence(
    context: CriticContext,
) -> bool:
    return (
        context.output_intent.docx_output_mode == "template_fill_docx"
        and not _spec_uses_template_fill(context.spec)
    )


_TEMPLATE_FILL_DOCX_REQUIRES_TEMPLATE_FILL_STEP = CriticInvariant(
    id="template_fill_docx_requires_template_fill_step",
    kind="architecture",
    description=(
        "Template-based DOCX generation must include a step with "
        "`output_mode=template_fill`."
    ),
    evidence=_template_fill_docx_requires_template_fill_step_evidence,
    remediation=(
        "Konversationen efterfrågar mallbaserad DOCX-generering men planen saknar ett steg med "
        '`output_mode="template_fill"`. Använd template_fill när ett Word-dokument ska fyllas från en mall.'
    ),
)


def _generated_docx_rejects_template_fill_evidence(context: CriticContext) -> bool:
    return (
        context.output_intent.docx_output_mode == "generated_docx"
        and _spec_uses_template_fill(context.spec)
    )


_GENERATED_DOCX_REJECTS_TEMPLATE_FILL = CriticInvariant(
    id="generated_docx_rejects_template_fill",
    kind="architecture",
    description=(
        "Generated DOCX (no template) must not use `output_mode=template_fill`."
    ),
    evidence=_generated_docx_rejects_template_fill_evidence,
    remediation=(
        "Konversationen efterfrågar genererad DOCX utan mall, men planen använder fortfarande "
        '`output_mode="template_fill"`. Använd inte template_fill när användaren uttryckligen '
        "valt genererad DOCX utan mall."
    ),
)


# ── Mixed-audio + document edit guardrails ───────────────────────────────


def _mixed_audio_doc_rejects_file_degradation_evidence(
    context: CriticContext,
) -> bool:
    if not context.mixed_audio_doc_input:
        return False
    return degrades_document_entry_to_generic_file(context.spec, flow=context.flow)


_MIXED_AUDIO_DOC_REJECTS_FILE_DEGRADATION = CriticInvariant(
    id="mixed_audio_doc_rejects_file_degradation",
    kind="architecture",
    description=(
        "When the user wants to add audio alongside an existing document flow, "
        "the plan must not degrade the document entry to a generic file input."
    ),
    evidence=_mixed_audio_doc_rejects_file_degradation_evidence,
    remediation=(
        "Användaren verkar vilja lägga till ljud/transkribering ovanpå ett befintligt dokumentflöde, "
        'men planen degraderar den dokumentbaserade ingången till generisk `input_type="file"`. '
        "Gör inte om ett dokumentflöde till allmän filinput bara för att få plats med ljud."
    ),
)


def _mixed_audio_doc_rejects_pseudo_transcription_evidence(
    context: CriticContext,
) -> bool:
    if not context.mixed_audio_doc_input:
        return False
    return uses_pseudo_transcription_without_audio_step(context.spec)


_MIXED_AUDIO_DOC_REJECTS_PSEUDO_TRANSCRIPTION = CriticInvariant(
    id="mixed_audio_doc_rejects_pseudo_transcription",
    kind="architecture",
    description=(
        "Mixed audio/document edits must not fake transcription inside a "
        "non-audio step instead of adding a real transcription step."
    ),
    evidence=_mixed_audio_doc_rejects_pseudo_transcription_evidence,
    remediation=(
        "Planen beskriver transkribering i instruktionerna men saknar ett riktigt "
        'transkriberingssteg (`input_type="audio"`, `output_mode="transcribe_only"`, '
        '`output_type="text"`). Faka inte transkribering inne i ett dokument- eller JSON-steg.'
    ),
)


def _mixed_audio_doc_requires_real_transcription_step_evidence(
    context: CriticContext,
) -> bool:
    if not context.mixed_audio_doc_input:
        return False
    return not has_real_audio_transcription_step(context.spec)


_MIXED_AUDIO_DOC_REQUIRES_REAL_TRANSCRIPTION_STEP = CriticInvariant(
    id="mixed_audio_doc_requires_real_transcription_step",
    kind="architecture",
    description=(
        "When the user combines audio transcription with documents, the plan "
        "must pick a single `flow_input` architecture — either keep documents "
        "primary or switch to audio-first with a real transcription step."
    ),
    evidence=_mixed_audio_doc_requires_real_transcription_step_evidence,
    remediation=(
        "När användaren vill kombinera ljudtranskribering och dokument i samma ändring måste planen "
        "först lösa inmatningsarkitekturen ärligt. Eneo-flöden stöder bara ett `flow_input`-steg, "
        "så planen ska antingen behålla dokument som primär indata eller byta till en riktig "
        "audio-first-arkitektur med ett transkriberingssteg — inte låtsas att båda ryms via prompttext."
    ),
)


# ── Public registry ──────────────────────────────────────────────────────


CRITIC_INVARIANTS: tuple[CriticInvariant, ...] = (
    _RUNTIME_METADATA_REQUIRES_FORM_FIELDS,
    _SECTIONED_FORM_INTAKE_REQUIRES_FORM_FIELDS,
    _RICH_WORKFLOW_REQUIRES_FORM_FIELDS,
    _RICH_WORKFLOW_REQUIRES_JSON_CONTRACT_STEP,
    _RICH_WORKFLOW_REQUIRES_MULTIPLE_STEPS,
    _PDF_TERMINAL_OUTPUT_ALIGNMENT,
    _DOCX_TERMINAL_OUTPUT_ALIGNMENT,
    _NON_TERMINAL_STEP_DOCUMENT_CONVERSION_FORBIDDEN,
    _NON_TERMINAL_STEP_TEMPLATE_FILL_FORBIDDEN,
    _STRUCTURED_EXTRACTION_REQUIRES_JSON_CONTRACT_STEP,
    _EXPLICIT_JSON_CONTRACT_REQUEST_WITHOUT_STEP,
    _STANDALONE_AUDIO_REQUIRES_TRANSCRIPTION_STEP,
    _FIELD_REUSE_REQUIRES_INPUT_BINDINGS,
    _MULTI_DOCUMENT_COMPARE_REQUIRES_ALL_PREVIOUS_STEPS,
    _MCP_SELECTION_REQUIRES_SEMANTIC_SUPPORT,
    _JSON_INPUT_REJECTS_ALL_PREVIOUS_STEPS_SOURCE,
    _PREFER_TARGETED_UNDERLAG_OVER_ALL_PREVIOUS_STEPS,
    _FINAL_TEXT_STEP_MUST_REFERENCE_RELEVANT_STRUCTURED_OUTPUTS,
    _FORM_FIELDS_DECLARED_MUST_BE_REFERENCED,
    _TEMPLATE_FILL_DOCX_REQUIRES_TEMPLATE_FILL_STEP,
    _GENERATED_DOCX_REJECTS_TEMPLATE_FILL,
    _MIXED_AUDIO_DOC_REJECTS_FILE_DEGRADATION,
    _MIXED_AUDIO_DOC_REJECTS_PSEUDO_TRANSCRIPTION,
    _MIXED_AUDIO_DOC_REQUIRES_REAL_TRANSCRIPTION_STEP,
)


def evaluate_critic_invariants(
    context: CriticContext,
    *,
    invariants: tuple[CriticInvariant, ...] = CRITIC_INVARIANTS,
) -> tuple[CriticIssue, ...]:
    return tuple(
        CriticIssue(
            id=invariant.id,
            kind=invariant.kind,
            remediation=invariant.remediation,
        )
        for invariant in invariants
        if invariant.evidence(context)
    )


def render_critic_issues(
    context: CriticContext,
    *,
    invariants: tuple[CriticInvariant, ...] = CRITIC_INVARIANTS,
) -> list[str]:
    return [
        issue.remediation
        for issue in evaluate_critic_invariants(context, invariants=invariants)
    ]


def enforce_architecture_critic_invariants(
    context: CriticContext,
    *,
    invariants: tuple[CriticInvariant, ...] = CRITIC_INVARIANTS,
) -> None:
    issues = tuple(
        issue
        for issue in evaluate_critic_invariants(context, invariants=invariants)
        if issue.kind == "architecture"
    )
    if not issues:
        return

    issue_ids = ",".join(issue.id for issue in issues)
    raise AIBuilderArchitectureError(
        public_code="architecture_critic_invariant_failed",
        detail=f"Architecture critic invariants failed: {issue_ids}",
        log_context={
            "critic_issue_ids": issue_ids,
            "critic_issue_count": len(issues),
            "flow_name": context.spec.flow_name,
            "step_count": len(context.spec.steps),
        },
    )
