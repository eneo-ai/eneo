"""Restraint signal: did the user ask for a plain text-to-text transform?

Only the user's own wording is read here. The requirements disclosure is a
localized projection of typed planning state, so scanning it for these markers
made the same typed state produce different plans in Swedish and English; the
planner reads typed state directly instead.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    form_field_intake_requested,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
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
    "avtal",
    "leverantörsavtal",
    "faktura",
    "fakturor",
    "contract",
    "contracts",
    "invoice",
    "invoices",
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

# An explicitly requested extra step is the exception the restraint's own
# wording promises ("om användaren inte uttryckligen ber om fler steg"); a
# one-step translation flow may be told to grow (2026-09-05). A request that
# mentions an extra step only to forbid it keeps the restraint.
_STEP_ADDITION_MARKERS: tuple[str, ...] = (
    "fler steg",
    "lägg till ett steg",
    "lägg till ett extra steg",
    "lägg till ett avslutande steg",
    "lägg till ett nytt steg",
    "ytterligare ett steg",
    "ytterligare steg",
    "ett steg till",
    "extra steg",
    "avslutande steg",
    "add a step",
    "add an extra step",
    "add a final step",
    "add another step",
    "additional step",
    "another step",
)

# Every negation names a step, so a prohibition on something else ("lägg
# inte till nya uppgifter", "do not add new facts") cannot cancel a requested
# step (gate 2026-09-05).
_STEP_ADDITION_NEGATION_MARKERS: tuple[str, ...] = (
    "utan extra steg",
    "utan ytterligare steg",
    "utan fler steg",
    "utan avslutande steg",
    "utan ett extra steg",
    "utan ett avslutande steg",
    "utan nya steg",
    "inga extra steg",
    "inga fler steg",
    "inga ytterligare steg",
    "inga nya steg",
    "inget extra steg",
    "inget avslutande steg",
    "inget nytt steg",
    "lägg inte till ett steg",
    "lägg inte till något steg",
    "lägg inte till fler steg",
    "lägg inte till extra steg",
    "lägg inte till nya steg",
    "lägg inte till ett extra steg",
    "lägg inte till ett avslutande steg",
    "lägg inte till ett nytt steg",
    "inte lägga till ett steg",
    "inte lägga till fler steg",
    "inte lägga till extra steg",
    "inte lägga till nya steg",
    "without extra steps",
    "without an extra step",
    "without additional steps",
    "without an additional step",
    "without another step",
    "without more steps",
    "without new steps",
    "do not add a step",
    "do not add another step",
    "do not add extra steps",
    "do not add an extra step",
    "do not add additional steps",
    "do not add more steps",
    "do not add new steps",
    "don't add a step",
    "don't add another step",
    "don't add extra steps",
    "don't add more steps",
    "no extra step",
    "no additional step",
    "no other step",
    "no new step",
    "no more steps",
    "not add another step",
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

_DIRECT_TEXT_TRANSFORM_MARKERS: tuple[str, ...] = (
    "översätt",
    "oversatt",
    "översätta",
    "oversatta",
    "översätter",
    "oversatter",
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
# Boundary matching avoids shrinking a flow because of substrings such as
# "rätta" inside "förrätta"; broader document markers are allowed to over-match.
_DIRECT_TEXT_TRANSFORM_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(marker) for marker in _DIRECT_TEXT_TRANSFORM_MARKERS)
    + r")\b"
)


def user_requested_simple_text_transform(
    text: str,
    *,
    model_form_intake_signals: Collection[str] = (),
) -> bool:
    """True when the user asked for one text-in/text-out transform and nothing more.

    Every exclusion below is something the user also said they wanted — source
    files, a document artefact, structured intermediates, a separate review
    pass, more steps than the minimum, or values to fill in at runtime. Any one
    of them means the plan is allowed more than a single step.
    """

    normalized = text.casefold()
    if not _DIRECT_TEXT_TRANSFORM_PATTERN.search(normalized):
        return False
    if form_field_intake_requested(
        normalized, model_form_intake_signals=model_form_intake_signals
    ):
        return False
    return not (
        _contains_any(normalized, _DOCUMENT_INPUT_MARKERS)
        or resolve_input_intent(normalized, {}).audio_requested
        or _contains_any(normalized, _DOCUMENT_OUTPUT_MARKERS)
        or _contains_any(normalized, _STRUCTURED_INTERMEDIATE_MARKERS)
        or _contains_any(normalized, _QUALITY_STEP_MARKERS)
        or _contains_any(normalized, _MULTI_STEP_PREFERENCE_MARKERS)
        or _requests_extra_step(normalized)
        or _contains_any(normalized, _FORM_COMPLEMENT_MARKERS)
        or _contains_any(normalized, _FORM_FIELD_GUARD_MARKERS)
    )


def _requests_extra_step(text: str) -> bool:
    """Affirmed step addition only; a forbidden extra step keeps the restraint."""

    if _contains_any(text, _STEP_ADDITION_NEGATION_MARKERS):
        return False
    return _contains_any(text, _STEP_ADDITION_MARKERS)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
