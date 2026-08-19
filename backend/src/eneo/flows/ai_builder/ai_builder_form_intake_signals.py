from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    runtime_input_fields_requested,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.planning_state import PlanningState

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

FORM_INTAKE_SIGNAL_ID = "form_intake_pattern"
FORM_INTAKE_NEEDS_FIELDS_SIGNAL = "needs_form_fields"
SECTIONED_FORM_INTAKE_SIGNAL = "sectioned_form_intake"


@dataclass(frozen=True, slots=True)
class FormIntakePattern:
    needs_form_fields: bool = False
    sectioned_form_intake: bool = False

    def recipe_signals(self) -> set[str]:
        signals: set[str] = set()
        if self.sectioned_form_intake:
            signals.add(SECTIONED_FORM_INTAKE_SIGNAL)
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


def form_intake_signal_values_from_planning_state(
    planning_state: "PlanningState | None",
) -> frozenset[str]:
    """The classifier's own form-intake verdict, as committed to planning state."""

    if planning_state is None:
        return frozenset()
    return frozenset(
        signal.value
        for signal in planning_state.signals
        if signal.question_id == FORM_INTAKE_SIGNAL_ID
    )


def form_intake_signal_evidence_from_planning_state(
    planning_state: "PlanningState | None",
) -> tuple[str, ...]:
    """The references the classifier cited for its form-intake verdict.

    Repair feedback has to name the fields the user asked for; a bare "add
    form fields" message once looped four identical proposals.
    """

    if planning_state is None:
        return ()
    return tuple(
        reference
        for signal in planning_state.signals
        if signal.question_id == FORM_INTAKE_SIGNAL_ID
        for reference in signal.provenance
    )


def form_field_intake_requested(
    text: str,
    *,
    model_form_intake_signals: Collection[str] = (),
) -> bool:
    """Did the user ask for values to fill in at runtime, in words or by answer?"""

    return (
        FORM_INTAKE_NEEDS_FIELDS_SIGNAL in model_form_intake_signals
        or SECTIONED_FORM_INTAKE_SIGNAL in model_form_intake_signals
        or mentions_form_field_needs(text)
    )


def sectioned_form_intake_requested(
    text: str,
    *,
    model_form_intake_signals: Collection[str] = (),
) -> bool:
    """Did the user ask to collect one free-text value per rubric or section?"""

    return SECTIONED_FORM_INTAKE_SIGNAL in model_form_intake_signals or (
        mentions_sectioned_form_intake(text)
    )


def _mentions_generic_form_field_need(text: str) -> bool:
    return any(token in text for token in _FORM_FIELD_NEED_MARKERS)


def _mentions_sectioned_form_intake(text: str) -> bool:
    if any(token in text for token in _OUTPUT_ONLY_SECTION_MARKERS):
        return False

    has_scope = any(token in text for token in _SECTION_SCOPE_MARKERS)
    has_input = any(token in text for token in _SECTION_INPUT_MARKERS)
    return has_scope and has_input
