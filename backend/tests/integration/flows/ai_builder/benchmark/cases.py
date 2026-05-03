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


class SlotCoverageTag(str, Enum):
    AUDIO = "audio"
    DOCUMENT = "document"
    AUDIO_DOCUMENT = "audio_document"
    TEXT_ONLY = "text_only"
    TEXT_UPLOAD = "text_upload"
    TRANSCRIPT_PROVIDED = "transcript_provided"
    STRUCTURED_EXTRACTION = "structured_extraction"
    COMPARISON = "comparison"
    # These prompts ask for JSON shaped for API consumers; FCM `http_post`
    # mechanics are covered by Flow-capability tests, not this slot corpus.
    HTTP_API = "http_api"
    MULTI_STEP = "multi_step"
    AMBIGUOUS = "ambiguous"


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


@dataclass(frozen=True, slots=True)
class SlotResolverCorpusCase:
    case_id: str
    ui_language: UiLanguage
    prompt: str
    expected_slots: tuple[ExpectedSlot, ...]
    coverage_tags: frozenset[SlotCoverageTag]


def _expected_slots(*pairs: tuple[str, str]) -> tuple[ExpectedSlot, ...]:
    return tuple(ExpectedSlot(name, value) for name, value in pairs)


def _coverage_tags(*tags: SlotCoverageTag) -> frozenset[SlotCoverageTag]:
    return frozenset(tags)


def _slot_resolver_case(
    case_id: str,
    prompt: str,
    expected_slots: tuple[ExpectedSlot, ...],
    coverage_tags: frozenset[SlotCoverageTag],
) -> SlotResolverCorpusCase:
    return SlotResolverCorpusCase(
        case_id=case_id,
        ui_language="sv",
        prompt=prompt,
        expected_slots=expected_slots,
        coverage_tags=coverage_tags,
    )


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


SLOT_RESOLVER_CORPUS_CASES: tuple[SlotResolverCorpusCase, ...] = (
    _slot_resolver_case(
        "slot_audio_docx_generated_01_sv",
        (
            "Användaren laddar upp en ljudfil som ska transkriberas. "
            "Slutresultatet ska vara ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
        ),
        _coverage_tags(SlotCoverageTag.AUDIO, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_audio_pdf_generated_02_sv",
        (
            "Ta emot en ljudfil vid körning, transkribera samtalet och "
            "skapa en vanlig PDF-rapport som slutresultat."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
        ),
        _coverage_tags(SlotCoverageTag.AUDIO, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_audio_text_summary_03_sv",
        (
            "Flödet ska ladda upp ljud, transkribera intervjun och ge en "
            "kort textsammanfattning med viktigaste punkterna."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "structured_text"),
        ),
        _coverage_tags(SlotCoverageTag.AUDIO, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_audio_json_output_04_sv",
        (
            "Ladda upp en ljudfil och transkribera den. Slutresultatet ska "
            "vara giltig JSON med talare, ämne och nästa steg."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_audio_structured_docx_05_sv",
        (
            "Bygg ett flöde för ljudfil där transkriberingen först blir "
            "strukturerad analys och sedan ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_audio_questions_text_06_sv",
        (
            "Användaren laddar upp en inspelning från en intervju. Flödet "
            "ska transkribera och skriva en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "structured_text"),
        ),
        _coverage_tags(SlotCoverageTag.AUDIO),
    ),
    _slot_resolver_case(
        "slot_audio_pdf_sections_07_sv",
        (
            "Ta emot en ljudfil, transkribera först och skapa sedan en "
            "PDF-rapport med rubriker för frågor, svar och uppföljning."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
        ),
        _coverage_tags(SlotCoverageTag.AUDIO, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_audio_docx_template_08_sv",
        (
            "Användaren laddar upp en ljudinspelning. Efter transkribering "
            "ska flödet fylla i en Word-mall med sammanfattning och citat."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
        ),
        _coverage_tags(
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_audio_document_ambiguous_09_sv",
        (
            "Jag har både en ljudfil och flera dokument och vill att flödet "
            "ska avgöra vilket material som ska styra analysen."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("document_material_scope", "multiple_documents_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.AUDIO_DOCUMENT,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.AMBIGUOUS,
        ),
    ),
    _slot_resolver_case(
        "slot_audio_document_docx_10_sv",
        (
            "Det finns en inspelning och ett uppladdat dokumentpaket. "
            "Slutresultatet ska vara ett Word-dokument, men primär indata "
            "behöver väljas."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("document_material_scope", "multiple_documents_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.AUDIO_DOCUMENT,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.AMBIGUOUS,
        ),
    ),
    _slot_resolver_case(
        "slot_document_single_text_01_sv",
        (
            "Användaren laddar upp ett dokument per körning och vill få en "
            "sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "single_document_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_multiple_text_02_sv",
        (
            "Ladda upp flera dokument i samma körning och skriv en "
            "sammanfattning som text av allt material."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "multiple_documents_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_document_flexible_pdf_03_sv",
        (
            "Flödet ska stödja både ett och flera dokument per körning och "
            "skapa en vanlig PDF-rapport."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "flexible_document_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_docx_template_04_sv",
        (
            "Användaren laddar upp ett dokument och en DOCX-mall. Flödet "
            "ska extrahera fakta och fylla mallen."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("document_material_scope", "single_document_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_document_docx_generated_05_sv",
        (
            "Ta emot uppladdade dokument och skapa ett Word-dokument utan "
            "mall med slutsatser, risker och rekommendationer."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_document_json_output_06_sv",
        (
            "Ladda upp en PDF och returnera strukturerad JSON med titel, "
            "datum, risker och rekommenderad nästa åtgärd."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_json"),
            ("document_material_scope", "single_document_case"),
            ("structured_analysis_need", "use_structured_analysis"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_document_metadata_basic_07_sv",
        (
            "Flödet tar emot uppladdade dokument och användaren ska också "
            "ange basic metadata vid körning. Slutresultatet är en "
            "sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "basic_case_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_metadata_detailed_08_sv",
        (
            "Användaren laddar upp dokument och fyller i inmatningsfält för "
            "referens, språk och målgrupp. Flödet skapar en rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "detailed_case_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_pdf_template_09_sv",
        (
            "Användaren laddar upp ett dokument och vill ha slutresultatet "
            "i en specifik PDF-mall med fast layout."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "pdf_template_requested"),
            ("document_material_scope", "single_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_multiple_pdf_10_sv",
        (
            "Ladda upp flera PDF:er, extrahera viktiga fakta och skapa en "
            "normal PDF utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "multiple_documents_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_document_one_contract_11_sv",
        (
            "Varje körning analyserar ett avtal åt gången, men materialet "
            "laddas upp som dokument. Skriv en rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "single_document_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_document_package_docx_12_sv",
        (
            "Ta emot ett dokumentpaket med flera relaterade filer, gör "
            "strukturerad analys och skapa ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("document_material_scope", "multiple_documents_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_text_only_summary_01_sv",
        (
            "Användaren klistrar in text och flödet skriver en "
            "sammanfattning som text. Ingen filuppladdning."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_text_only_json_02_sv",
        (
            "Ta emot text input vid körning och svara med giltig JSON med "
            "ämne, nyckelord och kort slutsats."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY, SlotCoverageTag.HTTP_API),
    ),
    _slot_resolver_case(
        "slot_text_only_docx_03_sv",
        (
            "Användaren klistrar in material som text och vill få ett "
            "Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_text_only_pdf_04_sv",
        (
            "Ta emot en kort text från användaren och skapa en vanlig "
            "PDF-rapport utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_text_only_polish_05_sv",
        (
            "Användaren klistrar in en rå text. Flödet ska skriva om den "
            "till tydligt språk och returnera sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_text_only_metadata_06_sv",
        (
            "Ta emot text input och låt användaren fylla i inmatningsfält "
            "för målgrupp och ton. Slutresultatet är en rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "detailed_case_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_text_only_template_docx_07_sv",
        (
            "Användaren klistrar in text och flödet ska fylla i en "
            "DOCX-mall med rubrik, sammanfattning och slutsats."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_ONLY, SlotCoverageTag.MULTI_STEP),
    ),
    _slot_resolver_case(
        "slot_text_only_structured_analysis_08_sv",
        (
            "Klistra in text, skapa först strukturerad analys och skriv "
            "sedan en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.TEXT_ONLY,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_text_upload_flexible_01_sv",
        (
            "Flödet ska stödja både inklistrad text och uppladdade dokument "
            "som källmaterial och skapa en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "flexible_document_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_UPLOAD, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_text_upload_docx_02_sv",
        (
            "Stöd både text input och uppladdade dokument. Slutresultatet "
            "ska vara ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_UPLOAD, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_text_upload_pdf_03_sv",
        (
            "Användaren kan antingen klistra in text eller ladda upp ett "
            "dokument och vill få en normal PDF som slutresultat."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_UPLOAD, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_text_upload_json_04_sv",
        (
            "Stöd inklistrad text och uppladdade dokument. Returnera "
            "strukturerad JSON med ämne, risker och rekommendationer."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_json"),
            ("document_material_scope", "flexible_document_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.TEXT_UPLOAD,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.HTTP_API,
        ),
    ),
    _slot_resolver_case(
        "slot_text_upload_metadata_05_sv",
        (
            "Flödet tar emot både text och dokument. Användaren fyller i "
            "inmatningsfält för referens och språk innan rapporten skrivs."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "detailed_case_metadata"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_UPLOAD, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_text_upload_template_06_sv",
        (
            "Användaren kan klistra in text eller ladda upp dokument. "
            "Flödet ska fylla i en Word-mall med sammanfattning och beslutspunkt."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.TEXT_UPLOAD,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_text_upload_multi_document_07_sv",
        (
            "Stöd både inklistrad text och flera uppladdade dokument per "
            "körning. Skriv en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "multiple_documents_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.TEXT_UPLOAD, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_text_upload_structured_pdf_08_sv",
        (
            "Ta emot text eller dokument, extrahera viktiga fakta som JSON "
            "innan slutrapporten och skapa en PDF-rapport."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "flexible_document_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.TEXT_UPLOAD,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_transcript_text_01_sv",
        (
            "Användaren har redan ett befintligt transkript och klistrar in "
            "det som text. Flödet skriver en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
        ),
        _coverage_tags(SlotCoverageTag.TRANSCRIPT_PROVIDED, SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_transcript_docx_02_sv",
        (
            "Materialet är redan transkriberat. Användaren klistrar in "
            "transkriptet och vill få ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
        ),
        _coverage_tags(SlotCoverageTag.TRANSCRIPT_PROVIDED, SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_transcript_json_03_sv",
        (
            "Ta emot ett befintligt transkript som text och returnera "
            "strukturerad JSON med ämne, citat och uppföljning."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(
            SlotCoverageTag.TRANSCRIPT_PROVIDED,
            SlotCoverageTag.TEXT_ONLY,
            SlotCoverageTag.HTTP_API,
        ),
    ),
    _slot_resolver_case(
        "slot_transcript_pdf_04_sv",
        (
            "Redan transkriberad text klistras in vid körning och flödet "
            "ska skapa en vanlig PDF-rapport."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
        ),
        _coverage_tags(SlotCoverageTag.TRANSCRIPT_PROVIDED, SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_transcript_structured_05_sv",
        (
            "Befintlig transkribering klistras in som text. Gör "
            "strukturerad analys och skriv sedan en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_text"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.TRANSCRIPT_PROVIDED,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_transcript_template_06_sv",
        (
            "Användaren klistrar in ett redan utskrivet samtal och flödet "
            "ska fylla i en DOCX-mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
        ),
        _coverage_tags(SlotCoverageTag.TRANSCRIPT_PROVIDED, SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_structured_document_report_01_sv",
        (
            "Ladda upp ett dokument, extrahera viktiga fakta som JSON innan "
            "slutrapporten och skriv en rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("structured_analysis_need", "use_structured_analysis"),
            ("document_material_scope", "single_document_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_document_docx_02_sv",
        (
            "Ta emot uppladdade dokument, extrahera nyckelfält som JSON och "
            "skapa ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_document_pdf_03_sv",
        (
            "Ladda upp flera dokument, gör strukturerad analys med risker "
            "och rekommendationer och skapa en PDF-rapport."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "multiple_documents_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_text_docx_04_sv",
        (
            "Klistra in text, extrahera strukturerad data där det "
            "förbättrar kvaliteten och skapa ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.TEXT_ONLY,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_text_json_05_sv",
        (
            "Text input ska analyseras och slutresultatet ska vara "
            "strukturerad JSON med namn, datum och slutsats."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_json"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.TEXT_ONLY,
            SlotCoverageTag.HTTP_API,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_audio_docx_06_sv",
        (
            "Ladda upp ljud, transkribera först, gör strukturerad analys "
            "och fyll sedan en Word-mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_no_extra_07_sv",
        (
            "Ladda upp dokument och håll analysen som vanlig text utan "
            "extra struktur. Slutresultatet ska vara en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("structured_analysis_need", "text_only_analysis"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_structured_metadata_08_sv",
        (
            "Ladda upp dokument, användaren fyller i inmatningsfält för "
            "fokus och språk, extrahera strukturerad data och skriv rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "detailed_case_metadata"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_api_output_09_sv",
        (
            "Ta emot uppladdade dokument och returnera machine readable JSON "
            "för ett API med fälten titel, risk och rekommendation."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_json"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.HTTP_API,
        ),
    ),
    _slot_resolver_case(
        "slot_structured_pdf_template_10_sv",
        (
            "Ladda upp ett dokument, extrahera strukturerad data och skapa "
            "slutresultatet i en specifik PDF-layout."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "pdf_template_requested"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.DOCUMENT,
        ),
    ),
    _slot_resolver_case(
        "slot_comparison_two_documents_01_sv",
        (
            "Jämför två uppladdade dokument i samma körning och skriv en "
            "sammanfattning som text av skillnaderna."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "multiple_documents_case"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        ),
        _coverage_tags(SlotCoverageTag.COMPARISON, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_comparison_multiple_pdf_02_sv",
        (
            "Ladda upp flera PDF:er, jämför dem direkt och skapa en "
            "PDF-rapport utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "multiple_documents_case"),
        ),
        _coverage_tags(SlotCoverageTag.COMPARISON, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_comparison_docx_03_sv",
        (
            "Jämför flera dokument i samma körning och skapa ett "
            "Word-dokument utan mall med likheter och skillnader."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("document_material_scope", "multiple_documents_case"),
        ),
        _coverage_tags(SlotCoverageTag.COMPARISON, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_comparison_json_04_sv",
        (
            "Ladda upp flera dokument och returnera strukturerad JSON som "
            "visar gemensamma punkter, skillnader och saknade uppgifter."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_json"),
            ("document_material_scope", "multiple_documents_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.COMPARISON,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
            SlotCoverageTag.HTTP_API,
        ),
    ),
    _slot_resolver_case(
        "slot_comparison_text_upload_05_sv",
        (
            "Jämför inklistrad text med uppladdade dokument och skriv en "
            "sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.COMPARISON,
            SlotCoverageTag.TEXT_UPLOAD,
            SlotCoverageTag.DOCUMENT,
        ),
    ),
    _slot_resolver_case(
        "slot_comparison_audio_document_06_sv",
        (
            "Jämför en transkribering från ljud med ett uppladdat dokument "
            "och skapa en rapport som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "single_document_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.COMPARISON,
            SlotCoverageTag.AUDIO_DOCUMENT,
            SlotCoverageTag.AMBIGUOUS,
        ),
    ),
    _slot_resolver_case(
        "slot_comparison_template_07_sv",
        ("Ladda upp flera dokument, jämför dem och fyll en DOCX-mall med resultatet."),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("document_material_scope", "multiple_documents_case"),
        ),
        _coverage_tags(SlotCoverageTag.COMPARISON, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_comparison_prior_material_08_sv",
        (
            "Jämför uppladdade dokument med tidigare sparat material och "
            "returnera en sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.COMPARISON, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_http_api_text_json_01_sv",
        (
            "Ta emot text input och returnera output as JSON så att ett "
            "API kan läsa ämne, status och rekommendation."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(SlotCoverageTag.HTTP_API, SlotCoverageTag.TEXT_ONLY),
    ),
    _slot_resolver_case(
        "slot_http_api_document_json_02_sv",
        (
            "Ladda upp dokument och svara med strukturerad JSON för ett API "
            "med fälten titel, datum och risk."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_json"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.HTTP_API, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_http_api_text_upload_json_03_sv",
        ("Stöd både text och dokument och returnera valid JSON till ett externt API."),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "structured_json"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.HTTP_API, SlotCoverageTag.TEXT_UPLOAD),
    ),
    _slot_resolver_case(
        "slot_http_api_audio_json_04_sv",
        (
            "Ladda upp ljud, transkribera och returnera JSON output med "
            "talare, ämne och uppföljning till ett API."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(
            SlotCoverageTag.HTTP_API,
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.MULTI_STEP,
        ),
    ),
    _slot_resolver_case(
        "slot_http_api_document_report_05_sv",
        (
            "Ladda upp en PDF, extrahera strukturerad data och returnera "
            "machine readable JSON till ett API."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_json"),
            ("structured_analysis_need", "use_structured_analysis"),
            ("document_material_scope", "single_document_case"),
        ),
        _coverage_tags(
            SlotCoverageTag.HTTP_API,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_http_api_transcript_json_06_sv",
        (
            "Klistra in ett befintligt transkript och returnera enbart JSON "
            "för vidare automation."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "structured_json"),
        ),
        _coverage_tags(
            SlotCoverageTag.HTTP_API,
            SlotCoverageTag.TRANSCRIPT_PROVIDED,
            SlotCoverageTag.TEXT_ONLY,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_document_chain_01_sv",
        (
            "Ladda upp dokument, extrahera viktiga fakta, skriv en "
            "målgruppsanpassad rapport och skapa ett Word-dokument utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_audio_chain_02_sv",
        (
            "Ladda upp ljud, transkribera, extrahera viktiga fakta och "
            "skapa en PDF-rapport."
        ),
        _expected_slots(
            ("primary_runtime_input", "audio"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.AUDIO,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_text_upload_chain_03_sv",
        (
            "Ta emot text eller dokument, skapa först JSON innan "
            "slutrapporten och fyll sedan en Word-mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text_and_documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.TEXT_UPLOAD,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_comparison_chain_04_sv",
        (
            "Ladda upp flera dokument, jämför dem direkt, extrahera "
            "skillnader och skapa en PDF-rapport utan mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "generated_pdf"),
            ("document_material_scope", "multiple_documents_case"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.COMPARISON,
            SlotCoverageTag.DOCUMENT,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_metadata_chain_05_sv",
        (
            "Användaren laddar upp dokument och fyller i inmatningsfält för "
            "fokus och deadline. Flödet extraherar fakta och skriver en "
            "sammanfattning som text."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("runtime_metadata_fields", "detailed_case_metadata"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.DOCUMENT,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_multistep_transcript_chain_06_sv",
        (
            "Klistra in en befintlig utskrift, skapa strukturerad analys "
            "och fyll sedan en DOCX-mall."
        ),
        _expected_slots(
            ("primary_runtime_input", "text"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "template_fill_docx"),
            ("structured_analysis_need", "use_structured_analysis"),
        ),
        _coverage_tags(
            SlotCoverageTag.MULTI_STEP,
            SlotCoverageTag.TRANSCRIPT_PROVIDED,
            SlotCoverageTag.STRUCTURED_EXTRACTION,
        ),
    ),
    _slot_resolver_case(
        "slot_ambiguous_material_01_sv",
        (
            "Jag vill analysera material och få ett användbart resultat, "
            "men jag vet inte om materialet blir text, ljud eller dokument."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("terminal_output", "unknown"),
        ),
        _coverage_tags(SlotCoverageTag.AMBIGUOUS),
    ),
    _slot_resolver_case(
        "slot_ambiguous_audio_document_02_sv",
        (
            "Källan kan vara inspelning eller uppladdade dokument beroende "
            "på körning. Fråga vad som ska vara primär indata."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("terminal_output", "unknown"),
        ),
        _coverage_tags(
            SlotCoverageTag.AMBIGUOUS,
            SlotCoverageTag.AUDIO_DOCUMENT,
        ),
    ),
    _slot_resolver_case(
        "slot_ambiguous_output_03_sv",
        ("Användaren laddar upp dokument, men slutformatet är inte valt ännu."),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "unknown"),
            ("document_material_scope", "flexible_document_case"),
        ),
        _coverage_tags(SlotCoverageTag.AMBIGUOUS, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_ambiguous_scope_04_sv",
        (
            "Flödet ska läsa uppladdade dokument och skapa en sammanfattning "
            "som text, men antal dokument per körning är oklart."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "structured_text"),
            ("document_material_scope", "unknown"),
        ),
        _coverage_tags(SlotCoverageTag.AMBIGUOUS, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_ambiguous_pdf_template_05_sv",
        (
            "Användaren laddar upp dokument och vill ha PDF, men det är "
            "oklart om en fast PDF-layout krävs."
        ),
        _expected_slots(
            ("primary_runtime_input", "documents"),
            ("terminal_output", "pdf_document"),
            ("pdf_generation_mode", "unknown"),
        ),
        _coverage_tags(SlotCoverageTag.AMBIGUOUS, SlotCoverageTag.DOCUMENT),
    ),
    _slot_resolver_case(
        "slot_ambiguous_audio_document_output_06_sv",
        (
            "Det kan finnas ljud och dokument i samma körning och "
            "slutresultatet kan vara text eller dokument. Flödet behöver "
            "ställa en tydlig följdfråga."
        ),
        _expected_slots(
            ("primary_runtime_input", "unknown"),
            ("terminal_output", "unknown"),
        ),
        _coverage_tags(
            SlotCoverageTag.AMBIGUOUS,
            SlotCoverageTag.AUDIO_DOCUMENT,
        ),
    ),
)
