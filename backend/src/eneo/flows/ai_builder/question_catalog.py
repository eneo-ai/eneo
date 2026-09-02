"""AI Builder Question Catalog — canonical bilingual user-facing copy.

A `QuestionTemplate` carries everything the UI needs to render a
discovery question for a single architectural slot: a bilingual (sv/en)
prompt, a bilingual help paragraph, a tuple of bilingual options, and
bilingual worked examples. No planner strategy, no FCM truth — that
surface belongs to the Pattern Registry and the FCM.

Catalog keys are slot names from
`ai_builder_slot_vocabulary.KNOWN_REQUIREMENT_SLOT_NAMES`. Pattern
Registry's `question_template_ids` field forward-references these keys;
the CI-enforced dangling-reference guard is
`test_every_question_template_id_resolves_in_catalog` in
`tests/unittests/flows/ai_builder/test_question_catalog.py`.

Copy is transcribed verbatim from the canonical factory functions in
`ai_builder_discovery_questions.py`. Option ids and values are preserved so
downstream answer-matching code is untouched.

This module is a pure leaf: its only non-stdlib import is the
slot-name frozenset from the dedicated leaf module
`ai_builder_slot_vocabulary.py`. An importlinter rule enforces this
boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    DiscoveryFamily,
    DiscoveryImpact,
)

Locale = Literal["sv", "en"]

QuestionExposure = Literal["user_requirement", "planner_internal"]


def runtime_metadata_field_details_question(locale: Locale) -> str:
    # The controls carry label, type, required and options; the question only
    # has to say who fills them in and when. Instructions to a developer are
    # not a question to a caseworker.
    if locale == "sv":
        return "Vad ska den som kör flödet fylla i?"
    return "What should the person running the flow fill in?"


def runtime_metadata_field_details_rationale(locale: Locale) -> str:
    """Why the fields matter — never a restatement of the question.

    Shown beside the question; the client omits the line when it is empty, so
    a rationale that only repeats the question would be worse than none.
    """

    if locale == "sv":
        return (
            "Fälten blir ett formulär som visas före varje körning. De blir också "
            "variabler som stegen kan använda i sina instruktioner."
        )
    return (
        "The fields become a form shown before every run. They also become "
        "variables the steps can use in their instructions."
    )


_RUNTIME_METADATA_FIELD_PURPOSE_LABELS: Mapping[str, tuple[str, str]] = (
    MappingProxyType(
        {
            "interpret_input": (
                "Använd för att förstå indata",
                "Use it to understand the input",
            ),
            "shape_result": (
                "Använd för att forma slutresultatet",
                "Use it to shape the final result",
            ),
            "whole_flow": (
                "Använd genom hela flödet",
                "Use it throughout the flow",
            ),
        }
    )
)

# The purposes a runtime field can serve, in the order the question offers
# them, read off the labels so a purpose can never be offered without words
# or carry words nobody can choose. The tokens are
# `planning_state.RuntimeMetadataFieldPurpose`, which this documented leaf
# cannot import; `test_ai_builder_turn_controller` checks the two agree.
RUNTIME_METADATA_FIELD_PURPOSES: tuple[str, ...] = tuple(
    _RUNTIME_METADATA_FIELD_PURPOSE_LABELS
)


def runtime_metadata_field_purpose_label(purpose: str, locale: Locale) -> str:
    """What a field's purpose is called, in the words the user chose it by.

    The confirmation card names the same purpose the question asked about, so
    both read this one owner. A second copy would let the card and the answer
    the user gave disagree about what a field is for.
    """

    label_sv, label_en = _RUNTIME_METADATA_FIELD_PURPOSE_LABELS[purpose]
    return label_sv if locale == "sv" else label_en


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """Single selectable option on a `QuestionTemplate`.

    Bilingual label + description so the UI can render either language
    without a runtime lookup. `value` is the canonical answer token the
    planner matches against.

    `example_*` says what choosing this option produces — the file the user
    ends up with, or what the flow does at run time — for a reader meeting
    the choice for the first time. It is optional and empty by default: some
    options have no honest concrete consequence to name, and an invented one
    would mislead the very reader it is written for. Written or left out in
    both languages together, so neither language shows an example the other
    is missing.
    """

    id: str
    label_sv: str
    label_en: str
    description_sv: str
    description_en: str
    value: str
    example_sv: str = ""
    example_en: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("QuestionOption id must be a non-empty string")
        if not self.value or not self.value.strip():
            raise ValueError("QuestionOption value must be a non-empty string")
        if not self.label_sv.strip():
            raise ValueError(f"QuestionOption {self.id!r}: label_sv must be non-empty")
        if not self.label_en.strip():
            raise ValueError(f"QuestionOption {self.id!r}: label_en must be non-empty")
        if not self.description_sv.strip():
            raise ValueError(
                f"QuestionOption {self.id!r}: description_sv must be non-empty"
            )
        if not self.description_en.strip():
            raise ValueError(
                f"QuestionOption {self.id!r}: description_en must be non-empty"
            )
        for locale, example in (("sv", self.example_sv), ("en", self.example_en)):
            if example != example.strip():
                # A blank-looking example is not the same as no example:
                # padding survives to the wire and shows the reader an empty
                # line where the consequence of the choice should be.
                raise ValueError(
                    f"QuestionOption {self.id!r}: example_{locale} must not be "
                    "padded or blank; leave it out instead"
                )
        if bool(self.example_sv) != bool(self.example_en):
            raise ValueError(
                f"QuestionOption {self.id!r}: example_sv and example_en must "
                "both be written or both be left out"
            )


@dataclass(frozen=True, slots=True)
class QuestionTemplate:
    """Canonical question attached to a single architectural slot.

    One template per slot name in `KNOWN_REQUIREMENT_SLOT_NAMES`.
    Today's `_build_catalog` only accepts exact slot-name keys; supporting
    multiple questions per slot would require an explicit key shape and a
    matching catalog build rule.

    `family`, `priority_base`, and `impact` are static discovery metadata
    for slot-backed questions. Lower priority wins; non-slot gates may
    interleave between catalog priorities in their own explicit maps.
    """

    id: str
    question_sv: str
    question_en: str
    help_sv: str
    help_en: str
    options: tuple[QuestionOption, ...]
    worked_examples_sv: tuple[str, ...]
    worked_examples_en: tuple[str, ...]
    family: DiscoveryFamily
    priority_base: int
    impact: DiscoveryImpact
    exposure: QuestionExposure = "user_requirement"
    allow_custom: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("QuestionTemplate id must be a non-empty string")
        if not self.question_sv.strip():
            raise ValueError(
                f"QuestionTemplate {self.id!r}: question_sv must be non-empty"
            )
        if not self.question_en.strip():
            raise ValueError(
                f"QuestionTemplate {self.id!r}: question_en must be non-empty"
            )
        if not self.help_sv.strip():
            raise ValueError(f"QuestionTemplate {self.id!r}: help_sv must be non-empty")
        if not self.help_en.strip():
            raise ValueError(f"QuestionTemplate {self.id!r}: help_en must be non-empty")
        if not self.options:
            raise ValueError(
                f"QuestionTemplate {self.id!r}: options must contain >=1 entry"
            )
        if not self.worked_examples_sv:
            raise ValueError(
                f"QuestionTemplate {self.id!r}: worked_examples_sv must "
                "contain >=1 entry"
            )
        if not self.worked_examples_en:
            raise ValueError(
                f"QuestionTemplate {self.id!r}: worked_examples_en must "
                "contain >=1 entry"
            )
        if self.priority_base < 0:
            raise ValueError(
                f"QuestionTemplate {self.id!r}: priority_base must be non-negative"
            )
        for example in self.worked_examples_sv:
            if not example.strip():
                raise ValueError(
                    f"QuestionTemplate {self.id!r}: blank string in worked_examples_sv"
                )
        for example in self.worked_examples_en:
            if not example.strip():
                raise ValueError(
                    f"QuestionTemplate {self.id!r}: blank string in worked_examples_en"
                )
        seen_option_ids: set[str] = set()
        for option in self.options:
            if option.id in seen_option_ids:
                raise ValueError(
                    f"QuestionTemplate {self.id!r}: duplicate option id {option.id!r}"
                )
            seen_option_ids.add(option.id)


def _option(
    *,
    id: str,
    label_sv: str,
    label_en: str,
    description_sv: str,
    description_en: str,
    value: str,
    example_sv: str = "",
    example_en: str = "",
) -> QuestionOption:
    return QuestionOption(
        id=id,
        label_sv=label_sv,
        label_en=label_en,
        description_sv=description_sv,
        description_en=description_en,
        value=value,
        example_sv=example_sv,
        example_en=example_en,
    )


_PRIMARY_RUNTIME_INPUT = QuestionTemplate(
    id="primary_runtime_input",
    question_sv="Vilket material ska flödet ta emot vid körning?",
    question_en="What source material should the flow accept at runtime?",
    help_sv=(
        "Ett flöde har en primär indata per körning. Välj det format som "
        "användaren faktiskt ska ladda upp eller klistra in."
    ),
    help_en=(
        "A flow has one primary runtime input per run. Pick the format the "
        "user will actually upload or paste."
    ),
    options=(
        _option(
            id="audio",
            label_sv="Ljud",
            label_en="Audio",
            description_sv="Ladda upp en ljudfil som ska transkriberas i flödet.",
            description_en="Upload an audio file that should be transcribed in the flow.",
            value="audio",
            example_sv="Flödet transkriberar ljudfilen till text före nästa steg.",
            example_en=(
                "The flow transcribes the audio file into text before the next step."
            ),
        ),
        _option(
            id="documents",
            label_sv="Dokument",
            label_en="Documents",
            description_sv="Ladda upp dokument som PDF, Word eller liknande filer.",
            description_en="Upload documents such as PDF or Word files.",
            value="documents",
            example_sv=(
                "Körningen börjar med att användaren laddar upp filer, till "
                "exempel Protokoll.pdf."
            ),
            example_en=(
                "A run starts with the user uploading files, for example Minutes.pdf."
            ),
        ),
        _option(
            id="json",
            label_sv="JSON",
            label_en="JSON",
            description_sv="Ta emot strukturerad JSON-data vid körning.",
            description_en="Accept structured JSON data at runtime.",
            value="json",
            example_sv="Ett annat system skickar in data; ingen fil laddas upp.",
            example_en="Another system sends in the data; no file is uploaded.",
        ),
        _option(
            id="text",
            label_sv="Text",
            label_en="Text",
            description_sv="Klistra in materialet direkt som text.",
            description_en="Paste the source material as text.",
            value="text",
            example_sv=(
                "Användaren klistrar in texten i ett fält i stället för att "
                "ladda upp en fil."
            ),
            example_en=(
                "The user pastes the text into a field instead of uploading a file."
            ),
        ),
        _option(
            id="text_and_documents",
            label_sv="Både text och dokument",
            label_en="Both text and documents",
            description_sv="Stöd både inklistrad text och uppladdade dokument.",
            description_en="Support both pasted text and uploaded documents.",
            value="text_and_documents",
            example_sv=(
                "Användaren kan både klistra in text och bifoga filer i samma körning."
            ),
            example_en="The user can both paste text and attach files in the same run.",
        ),
    ),
    worked_examples_sv=(
        "Uppladdning av mötesinspelning för transkribering.",
        "Användaren klistrar in en rapport som text.",
        "Ett annat system skickar in JSON-data.",
    ),
    worked_examples_en=(
        "Uploading a meeting recording for transcription.",
        "The user pastes a report as text.",
        "Another system sends in a JSON payload.",
    ),
    family="input_shape",
    priority_base=20,
    impact="architecture",
)


_TERMINAL_OUTPUT = QuestionTemplate(
    id="terminal_output",
    question_sv="Vad ska flödet producera som slutresultat?",
    question_en="What should the flow produce as the final output?",
    help_sv=(
        "Slutresultatet avgör vilka steg flödet kan ha. Strukturerad text "
        "och JSON är läs-för-människa respektive maskinläsbart; PDF och "
        "DOCX genererar dokument."
    ),
    help_en=(
        "The final output determines which steps the flow can use. "
        "Structured text and JSON are human-readable and machine-readable "
        "respectively; PDF and DOCX generate documents."
    ),
    options=(
        _option(
            id="structured_text",
            label_sv="Strukturerat textresultat",
            label_en="Structured text output",
            description_sv="Ett läsbart memo, rapport eller sammanfattning direkt i flödet.",
            description_en="A readable memo, report, or summary in the flow output.",
            value="structured_text",
            example_sv="Resultatet visas som läsbar text i flödet; ingen fil skapas.",
            example_en=(
                "The result appears as readable text in the flow; no file is created."
            ),
        ),
        _option(
            id="pdf_document",
            label_sv="PDF-dokument",
            label_en="PDF document",
            description_sv="Generera en PDF som slutresultat.",
            description_en="Generate a PDF document as the final output.",
            value="pdf_document",
            example_sv=(
                "Körningen slutar med en PDF-fil, till exempel Mötesrapport.pdf."
            ),
            example_en="The run ends with a PDF file, for example Meeting-report.pdf.",
        ),
        _option(
            id="docx_document",
            label_sv="DOCX-dokument",
            label_en="DOCX document",
            description_sv="Generera ett Word-dokument som slutresultat.",
            description_en="Generate a Word document as the final output.",
            value="docx_document",
            example_sv="Körningen slutar med en Word-fil som går att redigera vidare.",
            example_en="The run ends with a Word file that can be edited further.",
        ),
        _option(
            id="structured_json",
            label_sv="Strukturerad JSON",
            label_en="Structured JSON",
            description_sv="Maskinläsbara fält för vidare automation eller system.",
            description_en="Produce machine-readable fields for downstream systems.",
            value="structured_json",
            example_sv=(
                "Resultatet innehåller fält som kan skickas vidare till ett "
                "annat system."
            ),
            example_en=(
                "The result contains fields that can be sent on to another system."
            ),
        ),
    ),
    worked_examples_sv=(
        "Sammanfattning och bedömning som läsbart memo.",
        "Ifylld DOCX-mall som levereras till mottagaren.",
    ),
    worked_examples_en=(
        "Summary and assessment as a readable memo.",
        "Filled DOCX template delivered to the recipient.",
    ),
    family="output_artifact",
    priority_base=30,
    impact="architecture",
)


_DOCX_OUTPUT_MODE = QuestionTemplate(
    id="docx_output_mode",
    question_sv="Hur ska Word-dokumentet skapas?",
    question_en="How should the Word document be created?",
    help_sv=(
        "Word-dokumentet kan antingen skapas fritt utifrån analysen eller "
        "fyllas i i en befintlig mall. Välj mall om layouten är bestämd."
    ),
    help_en=(
        "The Word document can either be generated freely from the analysis "
        "or filled into an existing template. Pick template if the layout is fixed."
    ),
    options=(
        _option(
            id="generated_docx",
            label_sv="Genererat Word-dokument utan mall",
            label_en="Generated Word document without a template",
            description_sv="Skapa dokumentinnehållet direkt utan en fast mall.",
            description_en="Generate the document content directly without a fixed template.",
            value="generated_docx",
            example_sv=(
                "Dokumentet skapas från grunden; rubriker och layout följer innehållet."
            ),
            example_en=(
                "The document is created from scratch; headings and layout "
                "follow the content."
            ),
        ),
        _option(
            id="template_fill_docx",
            label_sv="Ifylld Word-mall",
            label_en="Filled-in Word template",
            description_sv="Fyll i en befintlig Word-mall med strukturerade fält.",
            description_en="Fill in an existing Word template with structured fields.",
            value="template_fill_docx",
            example_sv=(
                "Resultatet blir en ifylld version av er mall, med samma layout."
            ),
            example_en=(
                "The result is a filled-in copy of your template, with the same layout."
            ),
        ),
    ),
    worked_examples_sv=(
        "Genererad rapport utan mall.",
        "Ifyllning av organisationens Word-mall.",
    ),
    worked_examples_en=(
        "Generated report without a template.",
        "Filling the organization's Word template.",
    ),
    family="output_artifact",
    priority_base=70,
    impact="architecture",
)


_PDF_GENERATION_MODE = QuestionTemplate(
    id="pdf_generation_mode",
    question_sv="Kan resultatet vara en vanlig genererad PDF?",
    question_en="Can the result be a normal generated PDF?",
    help_sv=(
        "Eneo kan skapa en PDF utan fast mall, men kan inte fylla i en befintlig "
        "PDF-mall. Om en fast mall är ett krav kan ett flöde som bygger på en "
        "DOCX/Word-mall vara ett alternativ."
    ),
    help_en=(
        "Eneo can generate a PDF without a fixed template, but cannot fill an "
        "existing PDF template. If a fixed template is mandatory, a Flow based "
        "on a DOCX/Word template may be an alternative."
    ),
    options=(
        _option(
            id="generated_pdf",
            label_sv="Vanlig genererad PDF",
            label_en="Normal generated PDF",
            description_sv="Skapa en PDF direkt från analysen utan en fast mall.",
            description_en="Generate a PDF directly from the analysis without a fixed template.",
            value="generated_pdf",
            example_sv="PDF:en skapas från grunden, utan en förlaga att följa.",
            example_en="The PDF is created from scratch, without a layout to follow.",
        ),
        _option(
            id="pdf_template_requested",
            label_sv="Jag måste använda en specifik PDF-mall",
            label_en="I must use a specific PDF template",
            description_sv=(
                "Det stöds inte av Eneo i dag. Välj detta bara om kravet inte "
                "kan ändras; Eneo stoppar innan ett flöde skapas eller ändras."
            ),
            description_en=(
                "Eneo does not support this today. Choose this only if the "
                "requirement cannot change; Eneo will stop before creating or "
                "changing a Flow."
            ),
            value="pdf_template_requested",
        ),
    ),
    worked_examples_sv=(
        "Genererad sammanfattande PDF-rapport.",
        "Begärd fast PDF-layout för publicering.",
    ),
    worked_examples_en=(
        "Generated summary PDF report.",
        "Requested fixed PDF layout for publication.",
    ),
    family="output_artifact",
    priority_base=72,
    impact="architecture",
)


_DOCUMENT_MATERIAL_SCOPE = QuestionTemplate(
    id="document_material_scope",
    question_sv="Hur brukar underlaget per körning se ut?",
    question_en="For one run, what should the uploaded source material usually look like?",
    help_sv=(
        "Ett eller flera dokument per körning påverkar både uppladdnings"
        "steget och hur flödet läser materialet."
    ),
    help_en=(
        "One document or several per run affects both the upload step "
        "and how the flow reads the material."
    ),
    options=(
        _option(
            id="single_document_case",
            label_sv="Ett huvuddokument per körning",
            label_en="One main document per run",
            description_sv="Varje körning analyserar normalt ett primärt dokument.",
            description_en="Each run usually analyzes one primary PDF or document.",
            value="single_document_case",
            example_sv="Uppladdningen tar emot en fil per körning.",
            example_en="The upload step takes one file per run.",
        ),
        _option(
            id="multiple_documents_case",
            label_sv="Flera dokument i samma körning",
            label_en="Several documents in the same run",
            description_sv=(
                "Varje körning ska kunna hantera ett dokumentpaket med "
                "flera relaterade filer."
            ),
            description_en=(
                "Each run should handle a document package with multiple related files."
            ),
            value="multiple_documents_case",
            example_sv=(
                "Uppladdningen tar emot flera filer och flödet läser dem tillsammans."
            ),
            example_en=(
                "The upload step takes several files and the flow reads them together."
            ),
        ),
        _option(
            id="flexible_document_case",
            label_sv="Ibland ett, ibland flera dokument",
            label_en="Either one or several documents",
            description_sv="Flödet ska fungera både för en enskild fil och ett dokumentpaket.",
            description_en="The flow should work for both a single file and a document package.",
            value="flexible_document_case",
            example_sv=(
                "Samma flöde fungerar både för en enskild fil och för ett helt paket."
            ),
            example_en=(
                "The same flow works both for a single file and for a whole package."
            ),
        ),
    ),
    worked_examples_sv=(
        "En rapport per körning.",
        "Ett dokumentpaket med huvuddokument, svar och bilagor.",
    ),
    worked_examples_en=(
        "One report per run.",
        "A document package with primary document, response, and attachments.",
    ),
    family="input_shape",
    priority_base=50,
    impact="quality",
)


_COMPARISON_SCOPE = QuestionTemplate(
    id="comparison_scope",
    question_sv="När ska flödet jämföra dokument?",
    question_en="When should the flow compare documents?",
    help_sv=(
        "Valet avgör om dokument ska jämföras inom samma körning, mot tidigare "
        "sparat material eller inte alls."
    ),
    help_en=(
        "This decides whether documents are compared within the same run, "
        "against previously stored material, or not at all."
    ),
    options=(
        _option(
            id="same_run_compare",
            label_sv="Jämför dokument i samma körning",
            label_en="Compare documents in the same run",
            description_sv="Ladda upp flera dokument tillsammans och jämför dem direkt.",
            description_en="Upload several documents together and compare them directly.",
            value="same_run_compare",
            example_sv=(
                "Dokumenten som laddas upp tillsammans ställs mot varandra i "
                "samma körning."
            ),
            example_en=(
                "Documents uploaded together are set against each other in the "
                "same run."
            ),
        ),
        _option(
            id="compare_previous_material",
            label_sv="Jämför mot tidigare sparat material",
            label_en="Compare against earlier saved material",
            description_sv="Ladda upp ett dokument och jämför det mot tidigare material.",
            description_en="Upload one document and compare it to stored earlier material.",
            value="compare_previous_material",
        ),
        _option(
            id="no_direct_compare",
            label_sv="Ingen direkt jämförelse behövs",
            label_en="No direct comparison needed",
            description_sv="Analysera ett dokument i taget utan uttrycklig jämförelse.",
            description_en="Analyze one document at a time without explicit comparison.",
            value="no_direct_compare",
            example_sv=(
                "Inget jämförelsesteg läggs till; varje dokument bedöms för sig."
            ),
            example_en=(
                "No comparison step is added; each document is assessed on its own."
            ),
        ),
    ),
    worked_examples_sv=(
        "Jämför alla uppladdade anbud i samma körning.",
        "Bedöm ett nytt dokument mot tidigare sparade riktlinjer.",
    ),
    worked_examples_en=(
        "Compare all uploaded tenders in the same run.",
        "Assess a new document against previously stored guidance.",
    ),
    family="case_scope",
    priority_base=60,
    impact="architecture",
)


_REPORT_DISPOSITION = QuestionTemplate(
    id="report_disposition",
    question_sv="Hur ska rapporten hantera flera källdokument?",
    question_en="How should the report handle multiple source documents?",
    help_sv=(
        "När flera dokument laddas upp kan rapporten antingen ha ett avsnitt "
        "per källa, en samlad översikt eller båda."
    ),
    help_en=(
        "When several documents are uploaded, the report can either use one "
        "section per source, one synthesized overview, or both."
    ),
    options=(
        _option(
            id="per_source_sections",
            label_sv="Avsnitt per källa",
            label_en="Sections per source",
            description_sv="Skriv ett tydligt rapportavsnitt för varje uppladdat dokument.",
            description_en="Write a clear report section for each uploaded document.",
            value="per_source_sections",
            example_sv="Rapporten får en rubrik per uppladdat dokument.",
            example_en="The report gets one heading per uploaded document.",
        ),
        _option(
            id="synthesized_overview",
            label_sv="Samlad översikt",
            label_en="Synthesized overview",
            description_sv="Slå ihop källorna till en gemensam sammanfattning eller analys.",
            description_en="Combine the sources into one shared summary or analysis.",
            value="synthesized_overview",
            example_sv="Rapporten blir en sammanhållen text utan avsnitt per dokument.",
            example_en=(
                "The report becomes one coherent text without per-document sections."
            ),
        ),
        _option(
            id="both",
            label_sv="Både avsnitt och översikt",
            label_en="Both",
            description_sv="Ha källspecifika avsnitt och avsluta med en samlad slutsats.",
            description_en="Use source-specific sections and end with a synthesized conclusion.",
            value="both",
            example_sv=(
                "Rapporten får avsnitt per dokument och avslutas med en samlad "
                "bedömning."
            ),
            example_en=(
                "The report gets per-document sections and ends with an overall "
                "assessment."
            ),
        ),
    ),
    worked_examples_sv=(
        "En sektion för varje dokument, därefter en samlad bedömning.",
        "En kort helhetsbild utan separata dokumentavsnitt.",
    ),
    worked_examples_en=(
        "One section for each consultation response, then an overall assessment.",
        "A short overall view without separate document sections.",
    ),
    family="output_style",
    priority_base=55,
    impact="quality",
)


_POST_PROCESSING_GOAL = QuestionTemplate(
    id="post_processing_goal",
    question_sv="Vad ska flödet hjälpa dig göra med materialet?",
    question_en="What should the flow help you do with the material?",
    help_sv=(
        "Välj vad som ska hända efter att flödet har läst, transkriberat "
        "eller tolkat indata. Det avgör om flödet ska stanna vid "
        "grundresultatet eller bearbeta materialet vidare."
    ),
    help_en=(
        "Choose what should happen after the flow has read, transcribed, "
        "or interpreted the input. This determines whether the flow stops "
        "at the primary result or processes the material further."
    ),
    options=(
        _option(
            id="stop_after_primary_operation",
            label_sv="Bara grundresultatet",
            label_en="Only the primary result",
            description_sv="Stanna efter exempelvis transkription eller konvertering.",
            description_en="Stop after the transcript, conversion, or other primary result.",
            value="stop_after_primary_operation",
            example_sv=(
                "Du får grundresultatet, till exempel transkriptionen, utan "
                "vidare bearbetning."
            ),
            example_en=(
                "You get the primary result, for example the transcript, with "
                "no further processing."
            ),
        ),
        _option(
            id="summarize_or_overview",
            label_sv="Sammanfatta eller ge överblick",
            label_en="Summarize or give an overview",
            description_sv="Skapa en kortare sammanfattning eller översikt.",
            description_en="Create a shorter summary or overview.",
            value="summarize_or_overview",
            example_sv=(
                "Flödet lägger till ett steg som kortar ner materialet till en "
                "översikt."
            ),
            example_en=(
                "The flow adds a step that shortens the material into an overview."
            ),
        ),
        _option(
            id="extract_key_information",
            label_sv="Plocka ut nyckeluppgifter",
            label_en="Extract key information",
            description_sv="Hämta ut viktiga fakta, fält, datum, belopp eller liknande.",
            description_en="Extract important facts, fields, dates, amounts, or similar details.",
            value="extract_key_information",
            example_sv=(
                "Flödet plockar ut uppgifter som datum, belopp och namn ur materialet."
            ),
            example_en="The flow pulls out details such as dates, amounts, and names.",
        ),
        _option(
            id="structure_key_information",
            label_sv="Strukturera materialet",
            label_en="Structure the material",
            description_sv="Gör materialet till tydliga anteckningar, memo eller rapport.",
            description_en="Turn the material into clear notes, a memo, or a report.",
            value="structure_key_information",
            example_sv="Materialet skrivs om till ett ordnat memo med rubriker.",
            example_en="The material is rewritten as an ordered memo with headings.",
        ),
        _option(
            id="action_followup",
            label_sv="Beslut, nästa steg och uppföljning",
            label_en="Decisions, next steps, and follow-up",
            description_sv="Plocka ut beslut, åtgärder, ansvariga, deadlines och öppna frågor.",
            description_en="Extract decisions, actions, owners, deadlines, and open questions.",
            value="action_followup",
            example_sv=(
                "Resultatet blir en lista med beslut, åtgärder, ansvariga och datum."
            ),
            example_en=(
                "The result is a list of decisions, actions, owners, and dates."
            ),
        ),
        _option(
            id="decision_support",
            label_sv="Rekommendationer och vägval",
            label_en="Recommendations and guidance",
            description_sv="Ta fram rekommendationer eller nästa möjliga vägval.",
            description_en="Create recommendations or next possible choices.",
            value="decision_support",
            example_sv="Flödet föreslår vägval och motiverar dem utifrån materialet.",
            example_en=(
                "The flow suggests options and explains the reasoning based on "
                "the source material."
            ),
        ),
        _option(
            id="risk_or_issue_review",
            label_sv="Granska risker eller problem",
            label_en="Review risks or issues",
            description_sv="Identifiera risker, avvikelser, osäkerheter eller problem.",
            description_en="Identify risks, deviations, uncertainty, or problems.",
            value="risk_or_issue_review",
            example_sv=(
                "Resultatet blir en genomgång av risker och avvikelser i materialet."
            ),
            example_en=(
                "The result is a review of risks and deviations found in the material."
            ),
        ),
        _option(
            id="compare_or_validate",
            label_sv="Jämföra eller validera",
            label_en="Compare or validate",
            description_sv="Jämför mot annat underlag, regler, schema eller checklista.",
            description_en="Compare against other material, rules, a schema, or a checklist.",
            value="compare_or_validate",
            example_sv=(
                "Flödet ställer materialet mot regler eller annat underlag och "
                "visar avvikelser."
            ),
            example_en=(
                "The flow sets the material against rules or other sources and "
                "shows deviations."
            ),
        ),
    ),
    worked_examples_sv=(
        "Transkribera mötet och plocka ut beslut, nästa steg och ansvariga.",
        "Läs JSON och returnera fält enligt ett schema.",
    ),
    worked_examples_en=(
        "Transcribe the meeting and extract decisions, next steps, and owners.",
        "Read JSON and return fields according to a schema.",
    ),
    family="workflow_outcome",
    priority_base=28,
    impact="quality",
)


_STRUCTURED_IO_CONTRACT = QuestionTemplate(
    id="structured_io_contract",
    question_sv="Vad ska flödet göra med JSON-datan?",
    question_en="What should the flow do with the JSON data?",
    help_sv=(
        "När indata och resultat är JSON behöver flödet veta om datan ska "
        "mappas om, valideras, beräknas, normaliseras eller klassificeras."
    ),
    help_en=(
        "When input and result are JSON, the flow needs to know whether the "
        "data should be mapped, validated, computed, normalized, or classified."
    ),
    options=(
        _option(
            id="map_to_new_schema",
            label_sv="Mappa till nytt schema",
            label_en="Map to a new schema",
            description_sv="Välj, döp om eller flytta fält till en ny JSON-struktur.",
            description_en="Select, rename, or move fields into a new JSON shape.",
            value="map_to_new_schema",
            example_sv=(
                "Utdatan får de fältnamn och den struktur du anger, inte de inkommande."
            ),
            example_en=(
                "The output gets the field names and structure you specify, not "
                "the incoming ones."
            ),
        ),
        _option(
            id="validate_against_schema_or_rules",
            label_sv="Validera mot schema eller regler",
            label_en="Validate against schema or rules",
            description_sv="Kontrollera datan mot ett schema, regler eller krav.",
            description_en="Check the data against a schema, rules, or requirements.",
            value="validate_against_schema_or_rules",
            example_sv="Körningen rapporterar vad som saknas eller bryter mot reglerna.",
            example_en=(
                "The run reports what is missing or does not follow the rules."
            ),
        ),
        _option(
            id="extract_or_compute_fields",
            label_sv="Extrahera eller beräkna fält",
            label_en="Extract or compute fields",
            description_sv="Plocka ut, kombinera eller beräkna värden i JSON.",
            description_en="Extract, combine, or compute values in JSON.",
            value="extract_or_compute_fields",
            example_sv=(
                "Utdatan innehåller uträknade eller sammanställda värden, till "
                "exempel summor."
            ),
            example_en=(
                "The output contains computed or gathered values, for example totals."
            ),
        ),
        _option(
            id="normalize_or_enrich",
            label_sv="Normalisera eller berika",
            label_en="Normalize or enrich",
            description_sv="Städa, standardisera eller komplettera payloaden.",
            description_en="Clean, standardize, or enrich the payload.",
            value="normalize_or_enrich",
            example_sv=(
                "Utdatan får enhetliga format och fylls i där uppgifter saknas."
            ),
            example_en=(
                "The output uses consistent formats and fills gaps where possible."
            ),
        ),
        _option(
            id="classify_or_tag",
            label_sv="Klassificera eller tagga",
            label_en="Classify or tag",
            description_sv="Lägg till kategori, status, etiketter eller routingfält.",
            description_en="Add category, status, labels, or routing fields.",
            value="classify_or_tag",
            example_sv=(
                "Varje post får ett extra fält, till exempel kategori eller status."
            ),
            example_en=(
                "Each record gets an extra field, for example category or status."
            ),
        ),
        _option(
            id="custom_schema_or_rules",
            label_sv="Eget schema eller egna regler",
            label_en="Custom schema or rules",
            description_sv="Följ ett särskilt kontrakt som användaren beskriver.",
            description_en="Follow a specific contract described by the user.",
            value="custom_schema_or_rules",
        ),
    ),
    worked_examples_sv=(
        "Mappa inkommande order-JSON till organisationens exportschema.",
        "Validera payloaden mot regler och returnera fel som JSON.",
    ),
    worked_examples_en=(
        "Map incoming order JSON to the organization's export schema.",
        "Validate the payload against rules and return errors as JSON.",
    ),
    family="workflow_outcome",
    priority_base=27,
    impact="architecture",
)


_RUNTIME_METADATA_FIELDS = QuestionTemplate(
    id="runtime_metadata_fields",
    question_sv="Ska den som kör flödet också fylla i några extra uppgifter?",
    question_en="Should the person running the flow also fill in some extra details?",
    help_sv=(
        "Extra uppgifter är fält som fylls i utöver själva underlaget vid "
        "varje körning — till exempel referensnummer, språk eller ansvarig "
        "avdelning."
    ),
    help_en=(
        "Extra details are fields filled in beyond the source material "
        "itself at every run — for example a reference number, language, or "
        "responsible department."
    ),
    options=(
        _option(
            id="no_extra_metadata",
            label_sv="Inga extra fält",
            label_en="No extra fields",
            description_sv="Använd bara de uppladdade dokumenten som indata.",
            description_en="Use only the uploaded documents as input.",
            value="no_extra_metadata",
            example_sv=(
                "Användaren fyller inte i något formulär innan körningen startar."
            ),
            example_en=("The user fills in no form before the run starts."),
        ),
        _option(
            id="basic_runtime_metadata",
            label_sv="Några grundläggande fält",
            label_en="A few basic fields",
            description_sv="Den som kör flödet fyller i några enkla fält före körningen.",
            description_en="The person running the flow fills in a few simple fields before the run.",
            value="basic_runtime_metadata",
            example_sv=(
                "Några fält fylls i före körningen, till exempel ett referensnummer."
            ),
            example_en=(
                "The user fills in a few fields before the run starts, for "
                "example a reference number."
            ),
        ),
        _option(
            id="detailed_runtime_metadata",
            label_sv="Fler fält",
            label_en="More fields",
            description_sv=(
                "Samla in flera uppgifter, som referenser, språk, fokus, "
                "datum eller ansvarig avdelning."
            ),
            description_en=(
                "Collect several reusable inputs such as references, "
                "language, focus, dates, or responsible department."
            ),
            value="detailed_runtime_metadata",
            example_sv=(
                "Formuläret före körning får flera fält, som referensnummer, "
                "språk och enhet."
            ),
            example_en=(
                "The pre-run form gets several fields, such as a reference "
                "number, language and unit."
            ),
        ),
    ),
    worked_examples_sv=(
        "Fält för referensnummer och ansvarig enhet vid körning.",
        "Inga extra uppgifter — flödet arbetar enbart med det uppladdade materialet.",
    ),
    worked_examples_en=(
        "Runtime fields for reference number and responsible unit.",
        "No extra metadata — the flow works only with the uploaded material.",
    ),
    family="runtime_metadata",
    priority_base=100,
    impact="quality",
)


_MAPPED_FILE_LIMIT = QuestionTemplate(
    id="mapped_file_limit",
    question_sv="Hur många filer får en körning högst behandla?",
    question_en="How many files may one run process at most?",
    help_sv=("Bekräfta organisationens gräns eller ange ett lägre antal."),
    help_en=("Confirm the organization's limit or enter a lower number."),
    options=(
        _option(
            id="organization_limit",
            label_sv="Använd organisationens gräns",
            label_en="Use organization limit",
            description_sv="Använd den aktuella administratörskonfigurerade gränsen.",
            description_en="Use the current administrator-configured ceiling.",
            value="organization_limit",
            example_sv="Flödet följer den filgräns administratören har ställt in.",
            example_en=(
                "The flow follows the file limit the administrator has configured."
            ),
        ),
    ),
    worked_examples_sv=("Organisationens gräns", "3 filer per körning"),
    worked_examples_en=("Organization limit", "3 files per run"),
    family="input_shape",
    priority_base=25,
    impact="architecture",
    allow_custom=True,
)


_ALL_TEMPLATES: tuple[QuestionTemplate, ...] = (
    _PRIMARY_RUNTIME_INPUT,
    _MAPPED_FILE_LIMIT,
    _TERMINAL_OUTPUT,
    _DOCX_OUTPUT_MODE,
    _PDF_GENERATION_MODE,
    _DOCUMENT_MATERIAL_SCOPE,
    _COMPARISON_SCOPE,
    _REPORT_DISPOSITION,
    _POST_PROCESSING_GOAL,
    _STRUCTURED_IO_CONTRACT,
    _RUNTIME_METADATA_FIELDS,
)


def _build_catalog() -> Mapping[str, QuestionTemplate]:
    catalog: dict[str, QuestionTemplate] = {}
    for template in _ALL_TEMPLATES:
        if template.id in catalog:
            raise ValueError(f"Duplicate template id in seed: {template.id!r}")
        if template.id not in KNOWN_REQUIREMENT_SLOT_NAMES:
            raise ValueError(
                f"Template id {template.id!r} is not a known requirement slot "
                f"name; live vocabulary is "
                f"{sorted(KNOWN_REQUIREMENT_SLOT_NAMES)}"
            )
        catalog[template.id] = template
    missing = KNOWN_REQUIREMENT_SLOT_NAMES - catalog.keys()
    if missing:
        raise ValueError(
            f"Question Catalog missing templates for slot(s): {sorted(missing)}"
        )
    return MappingProxyType(catalog)


QUESTION_CATALOG: Mapping[str, QuestionTemplate] = _build_catalog()

_SUMMARY_LABELS_BY_LOCALE: Mapping[Locale, Mapping[str, str]] = MappingProxyType(
    {
        "sv": MappingProxyType(
            {
                "primary_runtime_input": "Indata vid körning",
                "mapped_file_limit": "Filgräns för upprepade steg",
                "terminal_output": "Slutresultat",
                "docx_output_mode": "Word-resultat",
                "pdf_generation_mode": "PDF-resultat",
                "document_material_scope": "Dokumentunderlag",
                "comparison_scope": "Jämförelse",
                "report_disposition": "Rapportupplägg",
                "post_processing_goal": "Syfte med bearbetningen",
                "structured_io_contract": "JSON-bearbetning",
                "runtime_metadata_fields": "Extra uppgifter vid körning",
            }
        ),
        "en": MappingProxyType(
            {
                "primary_runtime_input": "Runtime input",
                "mapped_file_limit": "File limit for repeated steps",
                "terminal_output": "Final output",
                "docx_output_mode": "Word output",
                "pdf_generation_mode": "PDF output",
                "document_material_scope": "Document source material",
                "comparison_scope": "Comparison",
                "report_disposition": "Report structure",
                "post_processing_goal": "Processing purpose",
                "structured_io_contract": "JSON processing",
                "runtime_metadata_fields": "Extra details at runtime",
            }
        ),
    }
)

for _locale, _summary_labels in _SUMMARY_LABELS_BY_LOCALE.items():
    if _summary_labels.keys() != QUESTION_CATALOG.keys():
        raise ValueError(
            f"Summary labels for {_locale!r} must cover every question catalog slot."
        )


def legal_slot_values(slot_name: str) -> frozenset[str]:
    template = QUESTION_CATALOG[slot_name]
    return frozenset(option.value for option in template.options)


def render_summary_label(slot_name: str, locale: Locale) -> str:
    """Return the concise bilingual label used in requirements summaries."""
    if locale not in ("sv", "en"):
        raise ValueError(f"Unsupported locale: {locale!r}. Expected 'sv' or 'en'.")
    return _SUMMARY_LABELS_BY_LOCALE[locale][slot_name]


@dataclass(frozen=True, slots=True)
class RenderedOption:
    """Locale-resolved option snapshot — what a UI surface displays."""

    id: str
    label: str
    description: str
    value: str
    # Empty when the catalog names no concrete consequence for this option.
    example: str = ""


@dataclass(frozen=True, slots=True)
class RenderedQuestion:
    """Locale-resolved question snapshot — the UX projection of a
    `QuestionTemplate` at a chosen locale.

    Separate from `QuestionTemplate` on purpose: the template is the
    bilingual canonical source; `RenderedQuestion` is the flat,
    single-locale view consumers render. Keeping them distinct prevents
    UX code from accidentally leaking bilingual fields into the
    surface layer.
    """

    id: str
    locale: Locale
    question: str
    help: str
    options: tuple[RenderedOption, ...]
    worked_examples: tuple[str, ...]
    allow_custom: bool


def _project_option(option: QuestionOption, locale: Locale) -> RenderedOption:
    if locale == "sv":
        return RenderedOption(
            id=option.id,
            label=option.label_sv,
            description=option.description_sv,
            value=option.value,
            example=option.example_sv,
        )
    if locale == "en":
        return RenderedOption(
            id=option.id,
            label=option.label_en,
            description=option.description_en,
            value=option.value,
            example=option.example_en,
        )
    raise ValueError(f"Unsupported locale: {locale!r}. Expected 'sv' or 'en'.")


def render_question(template_id: str, locale: Locale) -> RenderedQuestion:
    """Snapshot `QUESTION_CATALOG[template_id]` into `locale`.

    Raises `KeyError` for an unknown `template_id` — a typo should
    surface loudly. Raises `ValueError` for any locale outside the
    supported `Literal["sv", "en"]` contract; lax callers that slip a
    non-literal in at runtime fail loudly rather than silently falling
    back to English. Options and worked-example order is preserved from
    the template.
    """
    template = QUESTION_CATALOG[template_id]
    if locale == "sv":
        question = template.question_sv
        help_text = template.help_sv
        worked_examples = template.worked_examples_sv
    elif locale == "en":
        question = template.question_en
        help_text = template.help_en
        worked_examples = template.worked_examples_en
    else:
        raise ValueError(f"Unsupported locale: {locale!r}. Expected 'sv' or 'en'.")
    return RenderedQuestion(
        id=template.id,
        locale=locale,
        question=question,
        help=help_text,
        options=tuple(_project_option(option, locale) for option in template.options),
        worked_examples=worked_examples,
        allow_custom=template.allow_custom,
    )
