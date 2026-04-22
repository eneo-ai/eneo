from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    mentions_form_field_needs,
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
    "decision support",
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
    "formulärfält",
    "inmatningsfält",
    "kompletterande formulärfält",
    "kompletterande fält",
    "komplettera med",
    "förtydliga",
    "saknade uppgifter",
    "metadatafält",
    "metadata fields",
)

_RICH_DOCUMENT_WORKFLOW_SIGNAL = "rich_document_workflow"


@dataclass(frozen=True, slots=True)
class PlannerPatternSignals:
    needs_form_fields: bool = False
    prefers_structured_intermediate: bool = False
    prefers_quality_step: bool = False
    rich_document_workflow: bool = False

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
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    assumptions: Any = confirmed_requirements.get("assumptions") or []
    for note in assumptions:
        if isinstance(note, str) and note.strip():
            parts.append(note.strip())

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
    for note in manual_setup_notes:
        if isinstance(note, str) and note.strip():
            parts.append(note.strip())

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
    needs_form_fields = mentions_form_field_needs(normalized) or _contains_any(
        normalized, _FORM_COMPLEMENT_MARKERS
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
        prefers_structured_intermediate=prefers_structured_intermediate,
        prefers_quality_step=prefers_quality_step,
        rich_document_workflow=rich_document_workflow,
    )


def extract_planner_pattern_recipe_signals(text: str) -> set[str]:
    return detect_planner_pattern_signals(text).recipe_signals()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
