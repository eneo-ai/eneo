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
    if locale == "sv":
        return (
            "Vilka metadatafält ska användaren fylla i? Ange etikett/namn, typ, "
            "om fältet är obligatoriskt och val för listfält."
        )
    return (
        "Which metadata fields should the user fill in? Provide the label/name, "
        "type, requiredness, and options for select fields."
    )


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """Single selectable option on a `QuestionTemplate`.

    Bilingual label + description so the UI can render either language
    without a runtime lookup. `value` is the canonical answer token the
    planner matches against.
    """

    id: str
    label_sv: str
    label_en: str
    description_sv: str
    description_en: str
    value: str

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
) -> QuestionOption:
    return QuestionOption(
        id=id,
        label_sv=label_sv,
        label_en=label_en,
        description_sv=description_sv,
        description_en=description_en,
        value=value,
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
        ),
        _option(
            id="documents",
            label_sv="Dokument",
            label_en="Documents",
            description_sv="Ladda upp dokument som PDF, Word eller liknande filer.",
            description_en="Upload documents such as PDF or Word files.",
            value="documents",
        ),
        _option(
            id="json",
            label_sv="JSON",
            label_en="JSON",
            description_sv="Ta emot en strukturerad JSON-payload vid körning.",
            description_en="Accept a structured JSON payload at runtime.",
            value="json",
        ),
        _option(
            id="text",
            label_sv="Text",
            label_en="Text",
            description_sv="Klistra in materialet direkt som text.",
            description_en="Paste the source material as text.",
            value="text",
        ),
        _option(
            id="text_and_documents",
            label_sv="Både text och dokument",
            label_en="Both text and documents",
            description_sv="Stöd både inklistrad text och uppladdade dokument.",
            description_en="Support both pasted text and uploaded documents.",
            value="text_and_documents",
        ),
    ),
    worked_examples_sv=(
        "Uppladdning av mötesinspelning för transkribering.",
        "Användaren klistrar in en rapport som text.",
        "Ett annat system skickar in en JSON-payload.",
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
        ),
        _option(
            id="pdf_document",
            label_sv="PDF-dokument",
            label_en="PDF document",
            description_sv="Generera en PDF som slutresultat.",
            description_en="Generate a PDF document as the final output.",
            value="pdf_document",
        ),
        _option(
            id="docx_document",
            label_sv="DOCX-dokument",
            label_en="DOCX document",
            description_sv="Generera ett Word-dokument som slutresultat.",
            description_en="Generate a Word document as the final output.",
            value="docx_document",
        ),
        _option(
            id="structured_json",
            label_sv="Strukturerad JSON",
            label_en="Structured JSON",
            description_sv="Maskinläsbara fält för vidare automation eller system.",
            description_en="Produce machine-readable fields for downstream systems.",
            value="structured_json",
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
    question_sv="Hur ska DOCX-resultatet skapas?",
    question_en="How should the DOCX output be created?",
    help_sv=(
        "DOCX kan antingen genereras fritt från analysen eller fyllas in i "
        "en befintlig mall. Välj mall om layouten är fast."
    ),
    help_en=(
        "DOCX can either be generated freely from the analysis or filled "
        "into an existing template. Pick template if the layout is fixed."
    ),
    options=(
        _option(
            id="generated_docx",
            label_sv="Genererad DOCX utan mall",
            label_en="Generated DOCX without template",
            description_sv="Skapa dokumentinnehållet direkt utan en fast mall.",
            description_en="Generate the document content directly without a fixed template.",
            value="generated_docx",
        ),
        _option(
            id="template_fill_docx",
            label_sv="DOCX från mall",
            label_en="DOCX from template",
            description_sv="Fyll en befintlig DOCX-mall med strukturerade fält.",
            description_en="Fill an existing DOCX template with structured fields.",
            value="template_fill_docx",
        ),
    ),
    worked_examples_sv=(
        "Genererad rapport utan mall.",
        "Ifyllning av organisationens DOCX-mall.",
    ),
    worked_examples_en=(
        "Generated report without a template.",
        "Filling the organization's DOCX template.",
    ),
    family="output_artifact",
    priority_base=70,
    impact="architecture",
)


_PDF_GENERATION_MODE = QuestionTemplate(
    id="pdf_generation_mode",
    question_sv="När du säger PDF-mall, vilket upplägg menar du?",
    question_en="When you say PDF template, which setup do you mean?",
    help_sv=(
        "Inbyggd mallfyllning finns bara för DOCX. Om slutresultatet måste "
        "följa en specifik PDF-layout hanteras mallen utanför flödet."
    ),
    help_en=(
        "Native template filling is only available for DOCX. If the final "
        "result must follow a specific PDF layout, the template is handled "
        "outside the flow."
    ),
    options=(
        _option(
            id="generated_pdf",
            label_sv="Vanlig genererad PDF",
            label_en="Normal generated PDF",
            description_sv="Skapa en PDF direkt från analysen utan en fast mall.",
            description_en="Generate a PDF directly from the analysis without a fixed template.",
            value="generated_pdf",
        ),
        _option(
            id="pdf_template_requested",
            label_sv="Specifik PDF-mall krävs",
            label_en="A specific PDF template is required",
            description_sv=(
                "Slutresultatet behöver följa en bestämd PDF-mall eller "
                "layout. Inbyggd mallfyllning stöds bara för DOCX/Word."
            ),
            description_en=(
                "The final result must follow a specific PDF template or "
                "layout. Native template filling is only supported for "
                "DOCX/Word."
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
        ),
        _option(
            id="flexible_document_case",
            label_sv="Ibland ett, ibland flera dokument",
            label_en="Either one or several documents",
            description_sv="Flödet ska fungera både för en enskild fil och ett dokumentpaket.",
            description_en="The flow should work for both a single file and a document package.",
            value="flexible_document_case",
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
        ),
        _option(
            id="synthesized_overview",
            label_sv="Samlad översikt",
            label_en="Synthesized overview",
            description_sv="Slå ihop källorna till en gemensam sammanfattning eller analys.",
            description_en="Combine the sources into one shared summary or analysis.",
            value="synthesized_overview",
        ),
        _option(
            id="both",
            label_sv="Både avsnitt och översikt",
            label_en="Both",
            description_sv="Ha källspecifika avsnitt och avsluta med en samlad slutsats.",
            description_en="Use source-specific sections and end with a synthesized conclusion.",
            value="both",
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
        ),
        _option(
            id="summarize_or_overview",
            label_sv="Sammanfatta eller ge överblick",
            label_en="Summarize or give an overview",
            description_sv="Skapa en kortare sammanfattning eller översikt.",
            description_en="Create a shorter summary or overview.",
            value="summarize_or_overview",
        ),
        _option(
            id="extract_key_information",
            label_sv="Plocka ut nyckeluppgifter",
            label_en="Extract key information",
            description_sv="Hämta ut viktiga fakta, fält, datum, belopp eller liknande.",
            description_en="Extract important facts, fields, dates, amounts, or similar details.",
            value="extract_key_information",
        ),
        _option(
            id="structure_key_information",
            label_sv="Strukturera materialet",
            label_en="Structure the material",
            description_sv="Gör materialet till tydliga anteckningar, memo eller rapport.",
            description_en="Turn the material into clear notes, a memo, or a report.",
            value="structure_key_information",
        ),
        _option(
            id="action_followup",
            label_sv="Beslut, nästa steg och uppföljning",
            label_en="Decisions, next steps, and follow-up",
            description_sv="Plocka ut beslut, åtgärder, ansvariga, deadlines och öppna frågor.",
            description_en="Extract decisions, actions, owners, deadlines, and open questions.",
            value="action_followup",
        ),
        _option(
            id="decision_support",
            label_sv="Rekommendationer och vägval",
            label_en="Recommendations and guidance",
            description_sv="Ta fram rekommendationer eller nästa möjliga vägval.",
            description_en="Create recommendations or next possible choices.",
            value="decision_support",
        ),
        _option(
            id="risk_or_issue_review",
            label_sv="Granska risker eller problem",
            label_en="Review risks or issues",
            description_sv="Identifiera risker, avvikelser, osäkerheter eller problem.",
            description_en="Identify risks, deviations, uncertainty, or problems.",
            value="risk_or_issue_review",
        ),
        _option(
            id="compare_or_validate",
            label_sv="Jämföra eller validera",
            label_en="Compare or validate",
            description_sv="Jämför mot annat underlag, regler, schema eller checklista.",
            description_en="Compare against other material, rules, a schema, or a checklist.",
            value="compare_or_validate",
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
    question_sv="Vad ska flödet göra mellan input-JSON och output-JSON?",
    question_en="What should the flow do between input JSON and output JSON?",
    help_sv=(
        "För maskinläsbara payloads behöver flödet veta om JSON ska mappas, "
        "valideras, beräknas, normaliseras eller klassificeras."
    ),
    help_en=(
        "For machine-readable payloads, the flow needs to know whether JSON "
        "should be mapped, validated, computed, normalized, or classified."
    ),
    options=(
        _option(
            id="map_to_new_schema",
            label_sv="Mappa till nytt schema",
            label_en="Map to a new schema",
            description_sv="Välj, döp om eller flytta fält till en ny JSON-struktur.",
            description_en="Select, rename, or move fields into a new JSON shape.",
            value="map_to_new_schema",
        ),
        _option(
            id="validate_against_schema_or_rules",
            label_sv="Validera mot schema eller regler",
            label_en="Validate against schema or rules",
            description_sv="Kontrollera payloaden mot ett schema, regler eller krav.",
            description_en="Check the payload against a schema, rules, or requirements.",
            value="validate_against_schema_or_rules",
        ),
        _option(
            id="extract_or_compute_fields",
            label_sv="Extrahera eller beräkna fält",
            label_en="Extract or compute fields",
            description_sv="Plocka ut, kombinera eller beräkna värden i JSON.",
            description_en="Extract, combine, or compute values in JSON.",
            value="extract_or_compute_fields",
        ),
        _option(
            id="normalize_or_enrich",
            label_sv="Normalisera eller berika",
            label_en="Normalize or enrich",
            description_sv="Städa, standardisera eller komplettera payloaden.",
            description_en="Clean, standardize, or enrich the payload.",
            value="normalize_or_enrich",
        ),
        _option(
            id="classify_or_tag",
            label_sv="Klassificera eller tagga",
            label_en="Classify or tag",
            description_sv="Lägg till kategori, status, etiketter eller routingfält.",
            description_en="Add category, status, labels, or routing fields.",
            value="classify_or_tag",
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
    question_sv="Ska användaren också ange metadata vid körning?",
    question_en="Should the user also enter metadata at runtime?",
    help_sv=(
        "Metadata är återanvändbara fält som användaren fyller i utöver "
        "själva underlaget — till exempel referensnummer, språk eller "
        "ansvarig avdelning."
    ),
    help_en=(
        "Metadata are reusable fields the user enters beyond the source "
        "material itself — for example reference number, language, or "
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
        ),
        _option(
            id="basic_case_metadata",
            label_sv="Lägg till grundläggande metadata",
            label_en="Add basic metadata",
            description_sv="Låt användaren ange några enkla återanvändbara fält.",
            description_en="Let the user enter a few simple reusable fields.",
            value="basic_case_metadata",
        ),
        _option(
            id="detailed_case_metadata",
            label_sv="Lägg till rikare metadatafält",
            label_en="Add richer metadata fields",
            description_sv=(
                "Samla flera återanvändbara fält som referenser, språk, "
                "fokus, datum eller ansvarig avdelning."
            ),
            description_en=(
                "Collect several reusable inputs such as references, "
                "language, focus, dates, or responsible department."
            ),
            value="detailed_case_metadata",
        ),
    ),
    worked_examples_sv=(
        "Fält för referensnummer och ansvarig enhet vid körning.",
        "Ingen extra metadata — flödet arbetar enbart med det uppladdade materialet.",
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
    question_sv="Hur många uppladdade filer ska ett mappat steg högst behandla?",
    question_en="How many uploaded files may a mapped step process at most?",
    help_sv=(
        "Bekräfta organisationens nuvarande gräns eller ange ett lägre positivt heltal."
    ),
    help_en=(
        "Confirm the organization's current ceiling or enter a lower positive integer."
    ),
    options=(
        _option(
            id="organization_limit",
            label_sv="Använd organisationens gräns",
            label_en="Use organization limit",
            description_sv="Använd den aktuella administratörskonfigurerade gränsen.",
            description_en="Use the current administrator-configured ceiling.",
            value="organization_limit",
        ),
    ),
    worked_examples_sv=("Organisationens gräns", "3 filer per körning"),
    worked_examples_en=("Organization limit", "3 files per run"),
    family="input_shape",
    priority_base=25,
    impact="architecture",
)


_ALL_TEMPLATES: tuple[QuestionTemplate, ...] = (
    _PRIMARY_RUNTIME_INPUT,
    _MAPPED_FILE_LIMIT,
    _TERMINAL_OUTPUT,
    _DOCX_OUTPUT_MODE,
    _PDF_GENERATION_MODE,
    _DOCUMENT_MATERIAL_SCOPE,
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


def legal_slot_values(slot_name: str) -> frozenset[str]:
    template = QUESTION_CATALOG[slot_name]
    return frozenset(option.value for option in template.options)


@dataclass(frozen=True, slots=True)
class RenderedOption:
    """Locale-resolved option snapshot — what a UI surface displays."""

    id: str
    label: str
    description: str
    value: str


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


def _project_option(option: QuestionOption, locale: Locale) -> RenderedOption:
    if locale == "sv":
        return RenderedOption(
            id=option.id,
            label=option.label_sv,
            description=option.description_sv,
            value=option.value,
        )
    if locale == "en":
        return RenderedOption(
            id=option.id,
            label=option.label_en,
            description=option.description_en,
            value=option.value,
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
    )
