from __future__ import annotations

from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    runtime_input_fields_requested,
)

_FORM_FIELD_NEED_MARKERS: tuple[str, ...] = (
    "ska kunna ange",
    "ska kunna välja",
    "ska fylla i",
    "fyll i",
    "ange följande",
    "önskat språk",
    "välja språk",
    "fokus för analysen",
    "kort beskrivning",
    "politisk nivå",
)

_SECTION_SCOPE_MARKERS: tuple[str, ...] = (
    "en sektion i taget",
    "för varje sektion",
    "per sektion",
    "under varje rubrik",
    "per rubrik",
    "separat per rubrik",
    "samma rubriker",
    "sektion för sektion",
    "rubrik för rubrik",
    "one section at a time",
    "for each section",
    "per section",
    "under each heading",
    "same headings",
)

_SECTION_INPUT_MARKERS: tuple[str, ...] = (
    "be användaren om fritext",
    "användaren om fritext",
    "fritext för varje sektion",
    "fritext för varje rubrik",
    "skriv fritext",
    "ange fritext",
    "samla in fritext",
    "mata in fritext",
    "user should provide free text",
    "free text for each section",
    "free text for each rubric",
    "free text under each heading",
    "enter free text",
    "provide free text",
)

_OUTPUT_ONLY_SECTION_MARKERS: tuple[str, ...] = (
    "slutrapporten ska innehålla rubrikerna",
    "rapporten ska innehålla rubrikerna",
    "slutdokumentet ska innehålla rubrikerna",
    "the final report should contain the headings",
    "the final document should contain the headings",
)

_SECTIONED_FORM_INTAKE_SIGNAL = "sectioned_form_intake"


@dataclass(frozen=True, slots=True)
class FormIntakePattern:
    needs_form_fields: bool = False
    sectioned_form_intake: bool = False

    def recipe_signals(self) -> set[str]:
        signals: set[str] = set()
        if self.sectioned_form_intake:
            signals.add(_SECTIONED_FORM_INTAKE_SIGNAL)
        return signals


def detect_form_intake_pattern(text: str) -> FormIntakePattern:
    normalized = text.casefold()
    if not normalized:
        return FormIntakePattern()

    sectioned_form_intake = _mentions_sectioned_form_intake(normalized)
    needs_form_fields = (
        sectioned_form_intake
        or _mentions_generic_form_field_need(normalized)
        or runtime_input_fields_requested(text)
    )
    return FormIntakePattern(
        needs_form_fields=needs_form_fields,
        sectioned_form_intake=sectioned_form_intake,
    )


def mentions_form_field_needs(text: str) -> bool:
    return detect_form_intake_pattern(text).needs_form_fields


def mentions_sectioned_form_intake(text: str) -> bool:
    return detect_form_intake_pattern(text).sectioned_form_intake


def extract_form_intake_recipe_signals(text: str) -> set[str]:
    return detect_form_intake_pattern(text).recipe_signals()


def _mentions_generic_form_field_need(text: str) -> bool:
    return any(token in text for token in _FORM_FIELD_NEED_MARKERS)


def _mentions_sectioned_form_intake(text: str) -> bool:
    if any(token in text for token in _OUTPUT_ONLY_SECTION_MARKERS):
        return False

    has_scope = any(token in text for token in _SECTION_SCOPE_MARKERS)
    has_input = any(token in text for token in _SECTION_INPUT_MARKERS)
    return has_scope and has_input
