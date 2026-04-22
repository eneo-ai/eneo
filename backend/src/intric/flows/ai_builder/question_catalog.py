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

`QUESTION_CATALOG_VERSION` is the monotonic integer stamped on persisted
plans and digests. Any catalog-surface change bumps it.

Copy is transcribed verbatim from the canonical factory functions in
`ai_builder_discovery_questions.py`. Option ids and values are
preserved so downstream answer-matching code is untouched, but two
templates (`primary_runtime_input`, `terminal_output`) keep slot-name
keys that differ from their legacy `DiscoveryQuestionSuggestion.question_id`
values (`input_material_mode`, `final_output_mode`); the downstream rewire
therefore needs a slot-key → legacy-question-id bridge for those two
rows; the remaining five migrate cleanly.

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

from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)

QUESTION_CATALOG_VERSION: int = 1

Locale = Literal["sv", "en"]


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """Single selectable option on a `QuestionTemplate`.

    Bilingual label + description so the UI can render either language
    without a runtime lookup. `value` is the canonical answer token the
    planner matches against (preserved from the legacy factory copy so
    downstream answer-handling stays identical).
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
    Today's `_build_catalog` only accepts exact slot-name keys; a
    future slice that wants multiple questions per slot needs to relax
    that build rule alongside introducing its own key shape.
    """

    id: str
    question_sv: str
    question_en: str
    help_sv: str
    help_en: str
    options: tuple[QuestionOption, ...]
    worked_examples_sv: tuple[str, ...]
    worked_examples_en: tuple[str, ...]

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
            description_en="Upload case documents such as PDF or Word files.",
            value="documents",
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
        "Handläggare klistrar in tjänsteskrivelse som text.",
    ),
    worked_examples_en=(
        "Uploading a meeting recording for transcription.",
        "Case officer pastes a report as text.",
    ),
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
            label_sv="Strukturerat beslutsunderlag som text",
            label_en="Structured decision support as text",
            description_sv="Ett läsbart memo eller beslutsunderlag direkt i flödet.",
            description_en="A readable memo or decision-support text in the flow output.",
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
        "Ifylld DOCX-mall till nämnden.",
    ),
    worked_examples_en=(
        "Summary and assessment as a readable memo.",
        "Filled DOCX template delivered to the board.",
    ),
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
        "Genererad tjänsteskrivelse utan mall.",
        "Ifyllning av kommunens beslutsmall.",
    ),
    worked_examples_en=(
        "Generated case report without a template.",
        "Filling the municipality's decision template.",
    ),
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
)


_DOCUMENT_MATERIAL_SCOPE = QuestionTemplate(
    id="document_material_scope",
    question_sv="Hur brukar underlaget för ett ärende se ut?",
    question_en="For one case, what should the uploaded source material usually look like?",
    help_sv=(
        "Ett eller flera dokument per ärende påverkar både uppladdnings"
        "steget och hur flödet läser materialet."
    ),
    help_en=(
        "One document or several per case affects both the upload step "
        "and how the flow reads the material."
    ),
    options=(
        _option(
            id="single_document_case",
            label_sv="Ett huvuddokument per ärende",
            label_en="One main document per case",
            description_sv="Varje körning analyserar normalt ett primärt dokument.",
            description_en="Each run usually analyzes one primary PDF or document.",
            value="single_document_case",
        ),
        _option(
            id="multiple_documents_case",
            label_sv="Flera dokument för samma ärende",
            label_en="Several documents for the same case",
            description_sv=(
                "Varje körning ska kunna hantera ett dokumentpaket med "
                "flera relaterade filer."
            ),
            description_en=(
                "Each run should handle a case package with multiple related files."
            ),
            value="multiple_documents_case",
        ),
        _option(
            id="flexible_document_case",
            label_sv="Ibland ett, ibland flera dokument",
            label_en="Either one or several documents",
            description_sv="Flödet ska fungera både för en enskild fil och ett dokumentpaket.",
            description_en="The flow should work for both a single file and a case package.",
            value="flexible_document_case",
        ),
    ),
    worked_examples_sv=(
        "En tjänsteskrivelse per ärende.",
        "Ett ärendepaket med remiss, svar och bilagor.",
    ),
    worked_examples_en=(
        "One case report per run.",
        "A case package with referral, response, and attachments.",
    ),
)


_STRUCTURED_ANALYSIS_NEED = QuestionTemplate(
    id="structured_analysis_need",
    question_sv=(
        "Ska flödet också ta fram strukturerad analys som kan återanvändas "
        "i senare steg?"
    ),
    question_en="Should the flow also produce structured analysis that later steps can reuse?",
    help_sv=(
        "Strukturerad analys betyder att flödet extraherar nyckelfält som "
        "JSON innan slutrapporten, så senare steg kan bygga vidare på dem."
    ),
    help_en=(
        "Structured analysis means the flow extracts key fields as JSON "
        "before the final report, so later steps can build on them."
    ),
    options=(
        _option(
            id="use_structured_analysis",
            label_sv="Ja, använd strukturerad analys där det förbättrar kvaliteten",
            label_en="Yes, use structured analysis where it improves quality",
            description_sv="Extrahera viktiga fält som JSON innan slutrapporten skrivs.",
            description_en="Extract important fields as JSON before writing the final report.",
            value="use_structured_analysis",
        ),
        _option(
            id="text_only_analysis",
            label_sv="Nej, håll analysen som vanlig text",
            label_en="No, keep the analysis as plain text",
            description_sv="Undvik extra struktur om den inte behövs.",
            description_en="Avoid extra structure if it is not needed.",
            value="text_only_analysis",
        ),
    ),
    worked_examples_sv=(
        "Extrahera part, datum och belopp innan slutrapporten.",
        "Skriv analysen direkt som löptext utan mellansteg.",
    ),
    worked_examples_en=(
        "Extract party, date, and amount before the final report.",
        "Write the analysis directly as prose without an intermediate step.",
    ),
)


_RUNTIME_METADATA_FIELDS = QuestionTemplate(
    id="runtime_metadata_fields",
    question_sv="Ska användaren också ange metadata vid körning?",
    question_en="Should the user also enter metadata at runtime?",
    help_sv=(
        "Metadata är återanvändbara fält som handläggaren fyller i utöver "
        "själva underlaget — till exempel ärendenummer, språk eller "
        "ansvarig avdelning."
    ),
    help_en=(
        "Metadata are reusable fields the case officer enters beyond the "
        "source material itself — for example case number, language, or "
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
        "Fält för diarienummer och ansvarig enhet vid körning.",
        "Ingen extra metadata — flödet arbetar enbart med det uppladdade materialet.",
    ),
    worked_examples_en=(
        "Runtime fields for case number and responsible unit.",
        "No extra metadata — the flow works only with the uploaded material.",
    ),
)


_ALL_TEMPLATES: tuple[QuestionTemplate, ...] = (
    _PRIMARY_RUNTIME_INPUT,
    _TERMINAL_OUTPUT,
    _DOCX_OUTPUT_MODE,
    _PDF_GENERATION_MODE,
    _DOCUMENT_MATERIAL_SCOPE,
    _STRUCTURED_ANALYSIS_NEED,
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
    return RenderedOption(
        id=option.id,
        label=option.label_en,
        description=option.description_en,
        value=option.value,
    )


def render_question(template_id: str, locale: Locale) -> RenderedQuestion:
    """Snapshot `QUESTION_CATALOG[template_id]` into `locale`.

    Raises `KeyError` for an unknown `template_id` — a typo should
    surface loudly. Options and worked-example order is preserved from
    the template; the Literal-typed `locale` parameter is the only
    branch point.
    """
    template = QUESTION_CATALOG[template_id]
    if locale == "sv":
        question = template.question_sv
        help_text = template.help_sv
        worked_examples = template.worked_examples_sv
    else:
        question = template.question_en
        help_text = template.help_en
        worked_examples = template.worked_examples_en
    return RenderedQuestion(
        id=template.id,
        locale=locale,
        question=question,
        help=help_text,
        options=tuple(_project_option(option, locale) for option in template.options),
        worked_examples=worked_examples,
    )


def question_ids_for_slot(slot: str) -> tuple[str, ...]:
    """Return every question-template id registered against `slot`.

    Today's catalog is one-template-per-slot, so the returned tuple has
    zero or one element. The plural return shape leaves room for a
    future slice that wants multiple questions per slot without a
    signature change. Unknown slot → `()` (the `"has this slot any
    copy?"` read is valid and must not raise).
    """
    if slot not in QUESTION_CATALOG:
        return ()
    return (slot,)
