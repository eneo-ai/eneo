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
        or _contains_any(normalized, _FORM_COMPLEMENT_MARKERS)
        or _contains_any(normalized, _FORM_FIELD_GUARD_MARKERS)
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
