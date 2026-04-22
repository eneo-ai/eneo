"""Conversation-spec alignment invariants consulted by the quality critic.

Each `CriticInvariant` is a self-contained triplet of
`(id, description, evidence, remediation)`. The quality critic calls
`render_critic_issues(context)`, which loops over a `CriticInvariant` tuple,
evaluates each `evidence` callable against a pre-built `CriticContext`, and
returns the `remediation` message for every invariant that fires. This
removes ad-hoc substring checks from the critic body — each invariant owns
its own evidence logic and Swedish prose.

Invariants are organized into clusters (`FORM_FIELDS_INVARIANTS`,
`TERMINAL_OUTPUT_INVARIANTS`, `DOCX_MODE_INVARIANTS`) so the critic can
evaluate one cluster at a time when issue ordering matters. `CRITIC_INVARIANTS`
is the flat default for call sites that want the full registry.

Layering: this module imports AI Builder types (`FlowDraftSpecCore`,
`OutputIntentResolution`, `PlannerPatternSignals`) and form-intake signals.
The Flow Capability Manifest stays engine-truth-only and does not learn
about conversation signals; those live here with the rest of the AI Builder
layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_sectioned_form_intake,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
    runtime_metadata_requested,
)
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    PlannerPatternSignals,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class CriticContext:
    """Pre-computed view of conversation + spec + flow used by every invariant.

    The critic builds the context once per call, then hands it to each
    `CriticInvariant.evidence` — invariants never re-parse the raw
    conversation.
    """

    spec: FlowDraftSpecCore
    flow: "Flow | None"
    answer_signals: dict[str, set[str]]
    text: str
    requirements_text: str
    signal_text: str
    planner_patterns: PlannerPatternSignals
    output_intent: OutputIntentResolution


CriticCheck = Callable[[CriticContext], bool]


@dataclass(frozen=True, slots=True)
class CriticInvariant:
    """Conversation-spec alignment invariant.

    `evidence(context)` returns True when the invariant is violated and the
    critic should surface `remediation` to the planner.
    """

    id: str
    description: str
    evidence: CriticCheck
    remediation: str


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


def _runtime_metadata_requires_form_fields_evidence(context: CriticContext) -> bool:
    return (
        runtime_metadata_requested(context.answer_signals)
        and not context.spec.form_fields
    )


_RUNTIME_METADATA_REQUIRES_FORM_FIELDS = CriticInvariant(
    id="runtime_metadata_requires_form_fields",
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
        and not context.spec.form_fields
    )


_RICH_WORKFLOW_REQUIRES_FORM_FIELDS = CriticInvariant(
    id="rich_workflow_requires_form_fields",
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


def _pdf_terminal_alignment_evidence(context: CriticContext) -> bool:
    if context.output_intent.terminal_output != "pdf_document":
        return False
    if not context.spec.steps:
        return False
    return context.spec.steps[-1].output_type != OutputType.PDF


_PDF_TERMINAL_OUTPUT_ALIGNMENT = CriticInvariant(
    id="pdf_terminal_output_alignment",
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


def _template_fill_docx_requires_template_fill_step_evidence(
    context: CriticContext,
) -> bool:
    return (
        context.output_intent.docx_output_mode == "template_fill_docx"
        and not _spec_uses_template_fill(context.spec)
    )


_TEMPLATE_FILL_DOCX_REQUIRES_TEMPLATE_FILL_STEP = CriticInvariant(
    id="template_fill_docx_requires_template_fill_step",
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


FORM_FIELDS_INVARIANTS: tuple[CriticInvariant, ...] = (
    _RUNTIME_METADATA_REQUIRES_FORM_FIELDS,
    _SECTIONED_FORM_INTAKE_REQUIRES_FORM_FIELDS,
    _RICH_WORKFLOW_REQUIRES_FORM_FIELDS,
    _RICH_WORKFLOW_REQUIRES_JSON_CONTRACT_STEP,
    _RICH_WORKFLOW_REQUIRES_MULTIPLE_STEPS,
)


TERMINAL_OUTPUT_INVARIANTS: tuple[CriticInvariant, ...] = (
    _PDF_TERMINAL_OUTPUT_ALIGNMENT,
    _DOCX_TERMINAL_OUTPUT_ALIGNMENT,
)


DOCX_MODE_INVARIANTS: tuple[CriticInvariant, ...] = (
    _TEMPLATE_FILL_DOCX_REQUIRES_TEMPLATE_FILL_STEP,
    _GENERATED_DOCX_REJECTS_TEMPLATE_FILL,
)


CRITIC_INVARIANTS: tuple[CriticInvariant, ...] = (
    *FORM_FIELDS_INVARIANTS,
    *TERMINAL_OUTPUT_INVARIANTS,
    *DOCX_MODE_INVARIANTS,
)


def render_critic_issues(
    context: CriticContext,
    *,
    invariants: tuple[CriticInvariant, ...] = CRITIC_INVARIANTS,
) -> list[str]:
    """Evaluate every invariant in `invariants` against `context` and collect
    the firing remediations in registration order.

    Pass one of the cluster tuples (`FORM_FIELDS_INVARIANTS`,
    `TERMINAL_OUTPUT_INVARIANTS`, `DOCX_MODE_INVARIANTS`) to evaluate one
    cluster at a time; omit the kwarg to evaluate the full `CRITIC_INVARIANTS`
    tuple.
    """
    return [inv.remediation for inv in invariants if inv.evidence(context)]
