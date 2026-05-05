from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_form_field_needs,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    user_relevant_requirement_notes,
    user_relevant_requirement_text,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    runtime_input_fields_declared_absent,
)

_DOCUMENT_INPUT_MARKERS: tuple[str, ...] = (
    "uppladdade dokument",
    "ladda upp dokument",
    "laddar upp dokument",
    "dokument per körning",
    "dokumentpaket",
    "underlag",
    "filer",
    "uploaded documents",
    "document package",
    "documents per run",
)

_DOCUMENT_OUTPUT_MARKERS: tuple[str, ...] = (
    "docx",
    "word",
    "pdf",
    "rapport",
    "report",
    "slutdokument",
    "slutligt dokument",
)

_STRUCTURED_INTERMEDIATE_MARKERS: tuple[str, ...] = (
    "json",
    "strukturerad data",
    "structured data",
    "strukturerad analys",
    "structured analysis",
    "output contract",
    "output_contract",
    "output_fields",
    "återanvänd",
    "reuse",
    "återanvändas",
    "extrahera",
    "extract",
)

_QUALITY_STEP_MARKERS: tuple[str, ...] = (
    "kvalitetssäkring",
    "kvalitetskontroll",
    "språkgranskning",
    "språkgranska",
    "granska",
    "validera",
    "review",
    "quality",
    "proofread",
    "qa",
)

_MULTI_STEP_PREFERENCE_MARKERS: tuple[str, ...] = (
    "flera steg",
    "mellanliggande steg",
    "inte bara minimal",
    "inte bara en minimal",
    "inte bara en kort kedja",
    "inte bara två steg",
    "not just a minimal",
    "not just two steps",
    "more than two steps",
)

_FORM_COMPLEMENT_MARKERS: tuple[str, ...] = (
    "kompletterande formulärfält",
    "kompletterande fält",
    "komplettera med",
    "förtydliga",
    "saknade uppgifter",
    "metadatafält",
    "metadata fields",
)
_FORM_FIELD_GUARD_MARKERS: tuple[str, ...] = (
    "runtime input field",
    "input field",
    "form field",
    "inmatningsfält",
    "formulärfält",
)
_DERIVE_FROM_INPUT_ONLY_MARKERS: tuple[str, ...] = (
    "baserat på transkriptionen",
    "utifrån transkriptionen",
    "från transkriptionen",
    "framgår av transkriptionen",
    "framgår tydligt av transkriptionen",
    "ej angivet i transkriptionen",
    "inte fråga användaren",
    "fråga inte användaren",
    "ska inte vara inmatningsfält",
    "derive from the transcript",
    "based on the transcript",
    "do not ask the user",
    "don't ask the user",
)

_RICH_DOCUMENT_WORKFLOW_SIGNAL = "rich_document_workflow"


_DIRECT_TEXT_TRANSFORM_MARKERS: tuple[str, ...] = (
    "översätt",
    "oversatt",
    "translate",
    "skriv om",
    "rewrite",
    "korrigera",
    "correct this",
    "rätta",
    "förkorta",
    "forkorta",
    "shorten",
    "sammanfatta den här",
    "sammanfatta denna",
    "summarize this",
    "summera den här",
    "summera denna",
)


@dataclass(frozen=True, slots=True)
class PlannerPatternSignals:
    """Conversation signals for both structure-seeking and restraint rules."""

    needs_form_fields: bool = False
    derive_from_input_only: bool = False
    prefers_structured_intermediate: bool = False
    prefers_quality_step: bool = False
    rich_document_workflow: bool = False
    is_simple_text_transform: bool = False

    def recipe_signals(self) -> set[str]:
        signals: set[str] = set()
        if self.rich_document_workflow:
            signals.add(_RICH_DOCUMENT_WORKFLOW_SIGNAL)
        return signals


def build_requirements_signal_text(
    confirmed_requirements: Mapping[str, Any] | None,
) -> str:
    if not confirmed_requirements:
        return ""

    parts: list[str] = []
    for key in ("summary", "input_description", "output_description"):
        value = confirmed_requirements.get(key)
        if isinstance(value, str):
            if relevant_value := user_relevant_requirement_text(value):
                parts.append(relevant_value)

    assumptions: Any = confirmed_requirements.get("assumptions") or []
    parts.extend(
        user_relevant_requirement_notes(
            note for note in assumptions if isinstance(note, str)
        )
    )

    key_decisions: Any = confirmed_requirements.get("key_decisions") or []
    for decision in key_decisions:
        if not isinstance(decision, Mapping):
            continue
        decision_map: Mapping[str, Any] = decision  # pyright: ignore[reportUnknownVariableType]
        topic = decision_map.get("topic")
        choice = decision_map.get("decision")
        if isinstance(topic, str) and topic.strip():
            parts.append(topic.strip())
        if isinstance(choice, str) and choice.strip():
            parts.append(choice.strip())

    manual_setup_notes: Any = confirmed_requirements.get("manual_setup_notes") or []
    parts.extend(
        user_relevant_requirement_notes(
            note for note in manual_setup_notes if isinstance(note, str)
        )
    )

    return "\n".join(parts)


def detect_planner_pattern_signals(text: str) -> PlannerPatternSignals:
    normalized = text.casefold()
    if not normalized:
        return PlannerPatternSignals()

    document_like_input = _contains_any(normalized, _DOCUMENT_INPUT_MARKERS)
    document_like_output = _contains_any(normalized, _DOCUMENT_OUTPUT_MARKERS)
    prefers_structured_intermediate = _contains_any(
        normalized, _STRUCTURED_INTERMEDIATE_MARKERS
    )
    prefers_quality_step = _contains_any(
        normalized, _QUALITY_STEP_MARKERS + _MULTI_STEP_PREFERENCE_MARKERS
    )
    derive_from_input_only = runtime_input_fields_declared_absent(
        normalized
    ) or _contains_any(
        normalized,
        _DERIVE_FROM_INPUT_ONLY_MARKERS,
    )
    needs_form_fields = (
        mentions_form_field_needs(normalized)
        or _contains_any(normalized, _FORM_COMPLEMENT_MARKERS)
    ) and not derive_from_input_only
    is_simple_text_transform = (
        _contains_any(normalized, _DIRECT_TEXT_TRANSFORM_MARKERS)
        and not document_like_input
        and not document_like_output
        and not prefers_structured_intermediate
        and not prefers_quality_step
        and not mentions_form_field_needs(normalized)
        and not _contains_any(normalized, _FORM_COMPLEMENT_MARKERS)
        and not _contains_any(normalized, _FORM_FIELD_GUARD_MARKERS)
    )
    rich_document_workflow = (
        document_like_input
        and document_like_output
        and (
            needs_form_fields or prefers_structured_intermediate or prefers_quality_step
        )
    )
    return PlannerPatternSignals(
        needs_form_fields=needs_form_fields,
        derive_from_input_only=derive_from_input_only,
        prefers_structured_intermediate=prefers_structured_intermediate,
        prefers_quality_step=prefers_quality_step,
        rich_document_workflow=rich_document_workflow,
        is_simple_text_transform=is_simple_text_transform,
    )


def extract_planner_pattern_recipe_signals(text: str) -> set[str]:
    return detect_planner_pattern_signals(text).recipe_signals()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
