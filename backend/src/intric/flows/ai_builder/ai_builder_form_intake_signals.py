from __future__ import annotations

_FORM_FIELD_NEED_MARKERS: tuple[str, ...] = (
    "ska kunna ange",
    "ska kunna välja",
    "ska fylla i",
    "fyll i",
    "ange följande",
    "önskat språk",
    "välja språk",
    "fokus för analysen",
    "ärendenummer",
    "kort beskrivning",
    "politisk nivå",
    "nämnd",
)

_SECTION_SCOPE_MARKERS: tuple[str, ...] = (
    "en sektion i taget",
    "för varje sektion",
    "per sektion",
    "under varje rubrik",
    "per rubrik",
    "separat per rubrik",
    "samma rubriker",
)

_SECTION_INPUT_MARKERS: tuple[str, ...] = (
    "be användaren om fritext",
    "användaren om fritext",
    "fritext för varje sektion",
    "fritext för varje rubrik",
    "skriv fritext",
    "ange fritext",
    "user should provide free text",
    "free text for each section",
    "free text under each heading",
    "enter free text",
)


def mentions_form_field_needs(text: str) -> bool:
    return any(token in text for token in _FORM_FIELD_NEED_MARKERS)


def mentions_sectioned_form_intake(text: str) -> bool:
    has_scope = any(token in text for token in _SECTION_SCOPE_MARKERS)
    has_input = any(token in text for token in _SECTION_INPUT_MARKERS)
    return has_scope and has_input
