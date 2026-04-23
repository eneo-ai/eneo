"""Canonical benchmark cases for the AI Builder baseline harness.

Each case is a single-turn user prompt. The harness runs the deterministic
discovery pipeline against each and records structural metrics. Coverage
spans the documented archetypes (vague, rich, ambiguous, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Archetype = Literal[
    "vague",
    "rich",
    "attachment_heavy",
    "text_only",
    "audio",
    "document_comparison",
    "template_fill",
    "form_centric",
    "mixed_runtime_input",
    "json_pipeline",
]

UiLanguage = Literal["sv", "en"]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    archetype: Archetype
    ui_language: UiLanguage
    prompt: str


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="attachment_heavy_01_sv",
        archetype="attachment_heavy",
        ui_language="sv",
        prompt=(
            "Vi laddar upp tre PDF-dokument per körning: ansökan, "
            "bakgrundsdokument och ett policydokument. Flödet ska läsa "
            "alla tre och producera en sammanfattande rapport."
        ),
    ),
    BenchmarkCase(
        case_id="attachment_heavy_02_en",
        archetype="attachment_heavy",
        ui_language="en",
        prompt=(
            "Users upload four PDFs per run: an application form, two "
            "background memos, and a reference policy. The flow should "
            "read all uploaded documents and emit a single decision memo."
        ),
    ),
    BenchmarkCase(
        case_id="audio_01_sv",
        archetype="audio",
        ui_language="sv",
        prompt=(
            "Transkribera ett internt möte (ljudfil) och producera ett "
            "kort mötesprotokoll i text."
        ),
    ),
    BenchmarkCase(
        case_id="audio_02_en",
        archetype="audio",
        ui_language="en",
        prompt=(
            "Transcribe an interview audio file and summarize the key "
            "points as plain text."
        ),
    ),
    BenchmarkCase(
        case_id="document_comparison_01_sv",
        archetype="document_comparison",
        ui_language="sv",
        prompt=(
            "Jämför två PDF-versioner av en policy och lista vad som "
            "skiljer sig åt i text."
        ),
    ),
    BenchmarkCase(
        case_id="form_centric_01_sv",
        archetype="form_centric",
        ui_language="sv",
        prompt=(
            "Formulärintag med sektionerade formulärfält: bakgrund, mål, "
            "prioritet, riskbedömning. Flödet skriver en kort "
            "sammanfattning i text."
        ),
    ),
    BenchmarkCase(
        case_id="json_pipeline_01_sv",
        archetype="json_pipeline",
        ui_language="sv",
        prompt=(
            "Extrahera strukturerad JSON från ett uppladdat PDF-underlag "
            "(titel, sammanfattning, risk), återanvänd fälten och skriv "
            "en rapport i text."
        ),
    ),
    BenchmarkCase(
        case_id="json_pipeline_02_en",
        archetype="json_pipeline",
        ui_language="en",
        prompt=(
            "Extract structured JSON (title, summary, risk) from the "
            "uploaded document, reuse those fields, and compose a short "
            "decision memo in plain text."
        ),
    ),
    BenchmarkCase(
        case_id="mixed_runtime_input_01_sv",
        archetype="mixed_runtime_input",
        ui_language="sv",
        prompt=(
            "Formuläret tar användarens namn och referens-id som "
            "inmatningsfält, kombineras med ett uppladdat PDF-underlag "
            "och producerar en kort åtgärdsplan i text."
        ),
    ),
    BenchmarkCase(
        case_id="rich_01_sv",
        archetype="rich",
        ui_language="sv",
        prompt=(
            "Användaren laddar upp ett PDF-underlag. Flödet ska extrahera "
            "nyckelfält, producera en sammanfattning med risker och "
            "möjligheter, och generera en DOCX-rapport med användarens "
            "namn."
        ),
    ),
    BenchmarkCase(
        case_id="rich_02_en",
        archetype="rich",
        ui_language="en",
        prompt=(
            "Users upload multiple document PDFs. The flow should extract "
            "structured JSON fields, compose a policy summary with risk "
            "assessment, and generate a DOCX output with the analyst's "
            "name attached."
        ),
    ),
    BenchmarkCase(
        case_id="template_fill_01_sv",
        archetype="template_fill",
        ui_language="sv",
        prompt=(
            "Fyll i en DOCX-mall med data från ett uppladdat PDF-"
            "dokument. Mallen innehåller placeholders för namn, datum "
            "och sammanfattning."
        ),
    ),
    BenchmarkCase(
        case_id="template_fill_02_en",
        archetype="template_fill",
        ui_language="en",
        prompt=(
            "Fill a DOCX template with data from structured JSON input. "
            "The template has placeholders for reference id, applicant name, "
            "and decision rationale."
        ),
    ),
    BenchmarkCase(
        case_id="text_only_01_sv",
        archetype="text_only",
        ui_language="sv",
        prompt=(
            "Skriv om en inklistrad text till formellt språk utan att "
            "ändra innehållet. Ingen filuppladdning."
        ),
    ),
    BenchmarkCase(
        case_id="text_only_02_en",
        archetype="text_only",
        ui_language="en",
        prompt=(
            "Rewrite a pasted text in a concise, formal tone. No file "
            "upload, text in and text out."
        ),
    ),
    BenchmarkCase(
        case_id="vague_01_sv",
        archetype="vague",
        ui_language="sv",
        prompt="sammanfatta mitt dokument",
    ),
    BenchmarkCase(
        case_id="vague_02_en",
        archetype="vague",
        ui_language="en",
        prompt="make a flow please",
    ),
)
