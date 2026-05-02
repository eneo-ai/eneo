"""Canonical benchmark and reliability cases for AI Builder.

Prompt fixtures live in this module so discovery benchmarks and reliability
shape expectations do not drift into separate prompt owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)

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


class CorpusSource(str, Enum):
    REPORTED_FAILURE = "reported_failure"
    MANUAL_RUNBOOK = "manual_runbook"
    CAPTURED_TELEMETRY = "captured_telemetry"
    MANUAL_REPRODUCTION = "manual_reproduction"


class DomainCoupling(str, Enum):
    NEUTRAL = "neutral"
    REPRODUCES_SPECIFIC_FAILURE = "reproduces_specific_failure"


class BehavioralRisk(str, Enum):
    AUDIO_TRANSCRIPTION = "audio_transcription"
    MULTI_DOCUMENT_AGGREGATION = "multi_document_aggregation"
    SECTIONED_REPORT = "sectioned_report"
    STRUCTURED_DATA_TO_TEXT = "structured_data_to_text"
    TEMPLATE_FILL = "template_fill"


@dataclass(frozen=True, slots=True)
class ExpectedSlot:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class ExpectedStepShape:
    input_source: FlowInputSource
    input_type: FlowInputType
    output_type: FlowOutputType
    output_mode: FlowOutputMode


@dataclass(frozen=True, slots=True)
class ExpectedFlowShape:
    runtime_input: FlowInputType
    terminal_output: FlowOutputType
    steps: tuple[ExpectedStepShape, ...]


@dataclass(frozen=True, slots=True)
class ReliabilityCorpusCase:
    case_id: str
    source: CorpusSource
    ui_language: UiLanguage
    prompt: str
    expected_slots: tuple[ExpectedSlot, ...]
    expected_flow_shape: ExpectedFlowShape
    behavioral_risks: frozenset[BehavioralRisk]
    domain_coupling: DomainCoupling = DomainCoupling.NEUTRAL


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


RELIABILITY_CORPUS_CASES: tuple[ReliabilityCorpusCase, ...] = (
    ReliabilityCorpusCase(
        case_id="reported_audio_to_docx_sv",
        source=CorpusSource.REPORTED_FAILURE,
        ui_language="sv",
        prompt=(
            "Jag vill kunna skicka in en ljudinspelning, få den transkriberad "
            "och få ett Word-dokument som slutresultat."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "audio"),
            ExpectedSlot("terminal_output", "docx_document"),
            ExpectedSlot("docx_output_mode", "generated_docx"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.AUDIO,
            terminal_output=FlowOutputType.DOCX,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.AUDIO,
                    FlowOutputType.TEXT,
                    FlowOutputMode.TRANSCRIBE_ONLY,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.DOCX,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset(
            {
                BehavioralRisk.AUDIO_TRANSCRIPTION,
            }
        ),
        domain_coupling=DomainCoupling.REPRODUCES_SPECIFIC_FAILURE,
    ),
    ReliabilityCorpusCase(
        case_id="advanced_audio_meeting_docx_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt=(
            "Bygg ett flöde där användaren laddar upp en eller flera "
            "ljudinspelningar från ett möte. Flödet ska transkribera, "
            "identifiera beslut, åtgärder, ansvariga, datum och osäkra delar, "
            "och skapa ett Word-dokument från grunden med rubrikerna "
            "Sammanfattning, Beslut, Åtgärder, Risker och Citat som behöver "
            "kontrolleras."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "audio"),
            ExpectedSlot("terminal_output", "docx_document"),
            ExpectedSlot("docx_output_mode", "generated_docx"),
            ExpectedSlot("structured_analysis_need", "use_structured_analysis"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.AUDIO,
            terminal_output=FlowOutputType.DOCX,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.AUDIO,
                    FlowOutputType.TEXT,
                    FlowOutputMode.TRANSCRIBE_ONLY,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.JSON,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.JSON,
                    FlowOutputType.DOCX,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset(
            {
                BehavioralRisk.AUDIO_TRANSCRIPTION,
            }
        ),
    ),
    ReliabilityCorpusCase(
        case_id="advanced_multi_file_template_docx_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt=(
            "Bygg ett flöde där användaren laddar upp flera underlagsfiler "
            "och en Word-mall. Flödet ska läsa underlaget, extrahera "
            "huvudfakta, jämföra motstridiga uppgifter, fylla mallen med "
            "strukturerade avsnitt och markera vilka uppgifter som saknar "
            "stöd i underlaget."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "documents"),
            ExpectedSlot("terminal_output", "docx_document"),
            ExpectedSlot("docx_output_mode", "template_fill_docx"),
            ExpectedSlot("document_material_scope", "multiple_documents_case"),
            ExpectedSlot("structured_analysis_need", "use_structured_analysis"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.DOCUMENT,
            terminal_output=FlowOutputType.DOCX,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.DOCUMENT,
                    FlowOutputType.JSON,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.JSON,
                    FlowOutputType.DOCX,
                    FlowOutputMode.TEMPLATE_FILL,
                ),
            ),
        ),
        behavioral_risks=frozenset(
            {
                BehavioralRisk.MULTI_DOCUMENT_AGGREGATION,
                BehavioralRisk.TEMPLATE_FILL,
            }
        ),
    ),
    ReliabilityCorpusCase(
        case_id="advanced_report_pdf_sections_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt=(
            "Bygg ett flöde där användaren laddar upp en längre rapport. "
            "Flödet ska dela upp rapporten efter rubriker, sammanfatta varje "
            "del, lyfta fram rekommendationer och risker, skriva en kort "
            "målgruppsanpassad slutsats och skapa en PDF-rapport."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "documents"),
            ExpectedSlot("terminal_output", "pdf_document"),
            ExpectedSlot("pdf_generation_mode", "generated_pdf"),
            ExpectedSlot("document_material_scope", "single_document_case"),
            ExpectedSlot("structured_analysis_need", "use_structured_analysis"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.DOCUMENT,
            terminal_output=FlowOutputType.PDF,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.DOCUMENT,
                    FlowOutputType.JSON,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.JSON,
                    FlowOutputType.TEXT,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.PDF,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset(
            {
                BehavioralRisk.SECTIONED_REPORT,
                BehavioralRisk.STRUCTURED_DATA_TO_TEXT,
            }
        ),
    ),
    ReliabilityCorpusCase(
        case_id="vague_audio_docx_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt=(
            "Jag vill kunna skicka in en ljudinspelning och få ett bra "
            "Word-dokument tillbaka."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "audio"),
            ExpectedSlot("terminal_output", "docx_document"),
            ExpectedSlot("docx_output_mode", "generated_docx"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.AUDIO,
            terminal_output=FlowOutputType.DOCX,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.AUDIO,
                    FlowOutputType.TEXT,
                    FlowOutputMode.TRANSCRIBE_ONLY,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.DOCX,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset({BehavioralRisk.AUDIO_TRANSCRIPTION}),
    ),
    ReliabilityCorpusCase(
        case_id="vague_multi_file_docx_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt=(
            "Jag vill ladda upp flera filer och få en tydlig "
            "Word-sammanställning av dem."
        ),
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "documents"),
            ExpectedSlot("terminal_output", "docx_document"),
            ExpectedSlot("docx_output_mode", "generated_docx"),
            ExpectedSlot("document_material_scope", "multiple_documents_case"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.DOCUMENT,
            terminal_output=FlowOutputType.DOCX,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.DOCUMENT,
                    FlowOutputType.TEXT,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.DOCX,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset({BehavioralRisk.MULTI_DOCUMENT_AGGREGATION}),
    ),
    ReliabilityCorpusCase(
        case_id="vague_report_pdf_sv",
        source=CorpusSource.MANUAL_RUNBOOK,
        ui_language="sv",
        prompt="Jag har en rapport och vill dela upp den och få en PDF-sammanfattning.",
        expected_slots=(
            ExpectedSlot("primary_runtime_input", "documents"),
            ExpectedSlot("terminal_output", "pdf_document"),
            ExpectedSlot("pdf_generation_mode", "generated_pdf"),
            ExpectedSlot("document_material_scope", "single_document_case"),
            ExpectedSlot("structured_analysis_need", "use_structured_analysis"),
        ),
        expected_flow_shape=ExpectedFlowShape(
            runtime_input=FlowInputType.DOCUMENT,
            terminal_output=FlowOutputType.PDF,
            steps=(
                ExpectedStepShape(
                    FlowInputSource.FLOW_INPUT,
                    FlowInputType.DOCUMENT,
                    FlowOutputType.JSON,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.JSON,
                    FlowOutputType.TEXT,
                    FlowOutputMode.PASS_THROUGH,
                ),
                ExpectedStepShape(
                    FlowInputSource.PREVIOUS_STEP,
                    FlowInputType.TEXT,
                    FlowOutputType.PDF,
                    FlowOutputMode.PASS_THROUGH,
                ),
            ),
        ),
        behavioral_risks=frozenset(
            {
                BehavioralRisk.SECTIONED_REPORT,
                BehavioralRisk.STRUCTURED_DATA_TO_TEXT,
            }
        ),
    ),
)
