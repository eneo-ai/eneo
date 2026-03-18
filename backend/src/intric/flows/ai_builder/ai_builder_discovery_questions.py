from __future__ import annotations

from collections.abc import Callable

from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryQuestionOption,
    DiscoveryQuestionSuggestion,
)


def localized_text(language: DiscoveryLanguage, swedish: str, english: str) -> str:
    return swedish if language == "sv" else english


def _option(
    *,
    language: DiscoveryLanguage,
    id: str,
    swedish_label: str,
    english_label: str,
    swedish_description: str,
    english_description: str,
    value: str,
) -> DiscoveryQuestionOption:
    return DiscoveryQuestionOption(
        id=id,
        label=localized_text(language, swedish_label, english_label),
        description=localized_text(language, swedish_description, english_description),
        value=value,
    )


def processing_scope_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="processing_scope",
        question=localized_text(
            language,
            "Hur ska flödet hantera underlaget per körning?",
            "How should the flow handle the source material per run?",
        ),
        options=(
            _option(
                language=language,
                id="single_case",
                swedish_label="Ett ärende åt gången",
                english_label="One case at a time",
                swedish_description="Varje körning behandlar ett huvudärende, avtal eller materialpaket i taget.",
                english_description="Each run processes one main case, contract, or source package at a time.",
                value="single_case",
            ),
            _option(
                language=language,
                id="multiple_cases",
                swedish_label="Flera ärenden i samma körning",
                english_label="Multiple cases in one run",
                swedish_description="En körning ska kunna hantera flera separata ärenden eller materialpaket tillsammans.",
                english_description="One run should handle several separate cases or source packages together.",
                value="multiple_cases",
            ),
        ),
    )


def input_material_mode_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="input_material_mode",
        question=localized_text(
            language,
            "Vilket material ska flödet ta emot vid körning?",
            "What source material should the flow accept at runtime?",
        ),
        options=(
            _option(
                language=language,
                id="audio",
                swedish_label="Ljud",
                english_label="Audio",
                swedish_description="Ladda upp en ljudfil som ska transkriberas i flödet.",
                english_description="Upload an audio file that should be transcribed in the flow.",
                value="audio",
            ),
            _option(
                language=language,
                id="documents",
                swedish_label="Dokument",
                english_label="Documents",
                swedish_description="Ladda upp dokument som PDF, Word eller liknande filer.",
                english_description="Upload case documents such as PDF or Word files.",
                value="documents",
            ),
            _option(
                language=language,
                id="text",
                swedish_label="Text",
                english_label="Text",
                swedish_description="Klistra in materialet direkt som text.",
                english_description="Paste the source material as text.",
                value="text",
            ),
            _option(
                language=language,
                id="text_and_documents",
                swedish_label="Både text och dokument",
                english_label="Both text and documents",
                swedish_description="Stöd både inklistrad text och uppladdade dokument.",
                english_description="Support both pasted text and uploaded documents.",
                value="text_and_documents",
            ),
        ),
    )


def flow_input_architecture_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="flow_input_architecture",
        question=localized_text(
            language,
            "Flödet kan bara ha en primär filuppladdning vid körning. Hur vill du att vi hanterar ljud och dokument?",
            "The flow can only have one primary runtime file upload. How should it handle audio and documents?",
        ),
        options=(
            _option(
                language=language,
                id="document_primary_input",
                swedish_label="Behåll dokument som primär indata",
                english_label="Keep documents as the primary input",
                swedish_description="Behåll dokumentuppladdning i det här flödet. Ljud transkriberas då inte som en separat primär indata här.",
                english_description="Keep document upload in this flow. Audio will not be transcribed here as a separate primary runtime input.",
                value="document_primary_input",
            ),
            _option(
                language=language,
                id="audio_primary_input",
                swedish_label="Byt till ljud som primär indata",
                english_label="Switch to audio as the primary input",
                swedish_description="Flödet börjar med riktig ljudtranskribering. Dokument ingår då inte som separat primär uppladdning i samma körning.",
                english_description="The flow starts with real audio transcription. Documents then do not enter as a separate primary upload in the same run.",
                value="audio_primary_input",
            ),
            _option(
                language=language,
                id="generic_file_input",
                swedish_label="Ta emot ett blandat filpaket",
                english_label="Accept a mixed file package",
                swedish_description="Ta emot blandade filer med generell filindata, men utan att lova ett separat ljudtranskriberingssteg.",
                english_description="Accept mixed files with generic file input, but without promising a separate audio-transcription step.",
                value="generic_file_input",
            ),
        ),
    )


def document_kind_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="document_kind",
        question=localized_text(
            language,
            "Vilken typ av dokument ska flödet främst arbeta med?",
            "What kind of documents should the flow primarily work with?",
        ),
        options=(
            _option(
                language=language,
                id="case_documents",
                swedish_label="Ärendedokument och officiellt underlag",
                english_label="Case documents and official material",
                swedish_description="Tjänsteskrivelser, beslut, remisser, PM och annat officiellt material.",
                english_description="Reports, decisions, remisses, memos, and other official case files.",
                value="case_documents",
            ),
            _option(
                language=language,
                id="news_articles",
                swedish_label="Nyhets- eller artikelmaterial",
                english_label="News or article-like material",
                swedish_description="Artiklar, kommentarer och redaktionellt material.",
                english_description="Articles, commentary, and editorial-style documents.",
                value="news_articles",
            ),
            _option(
                language=language,
                id="contracts_agreements",
                swedish_label="Avtal eller överenskommelser",
                english_label="Contracts or agreements",
                swedish_description="Juridiska eller kommersiella dokument som avtal och bilagor.",
                english_description="Legal or commercial documents such as contracts and appendices.",
                value="contracts_agreements",
            ),
            _option(
                language=language,
                id="mixed_documents",
                swedish_label="Blandat dokumentpaket",
                english_label="A mixed document package",
                swedish_description="Flera olika dokumenttyper som hör till samma analys.",
                english_description="Several different document types that belong to the same analysis.",
                value="mixed_documents",
            ),
        ),
    )


def document_material_scope_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="document_material_scope",
        question=localized_text(
            language,
            "Hur brukar underlaget för ett ärende se ut?",
            "For one case, what should the uploaded source material usually look like?",
        ),
        options=(
            _option(
                language=language,
                id="single_document_case",
                swedish_label="Ett huvuddokument per ärende",
                english_label="One main document per case",
                swedish_description="Varje körning analyserar normalt ett primärt dokument.",
                english_description="Each run usually analyzes one primary PDF or document.",
                value="single_document_case",
            ),
            _option(
                language=language,
                id="multiple_documents_case",
                swedish_label="Flera dokument för samma ärende",
                english_label="Several documents for the same case",
                swedish_description="Varje körning ska kunna hantera ett dokumentpaket med flera relaterade filer.",
                english_description="Each run should handle a case package with multiple related files.",
                value="multiple_documents_case",
            ),
            _option(
                language=language,
                id="flexible_document_case",
                swedish_label="Ibland ett, ibland flera dokument",
                english_label="Either one or several documents",
                swedish_description="Flödet ska fungera både för en enskild fil och ett dokumentpaket.",
                english_description="The flow should work for both a single file and a case package.",
                value="flexible_document_case",
            ),
        ),
    )


def comparison_scope_conflict_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="comparison_scope",
        question=localized_text(
            language,
            "Du valde en fil per körning men vill också jämföra dokument. Vilken jämförelsearkitektur vill du ha?",
            "You chose one file per run but also want document comparison. Which comparison architecture do you want?",
        ),
        options=(
            _option(
                language=language,
                id="same_run_multiple_documents",
                swedish_label="Flera dokument i samma körning",
                english_label="Several documents in the same run",
                swedish_description="Ladda upp flera dokument tillsammans och jämför dem direkt.",
                english_description="Upload multiple documents together and compare them directly.",
                value="same_run_multiple_documents",
            ),
            _option(
                language=language,
                id="single_document_against_previous",
                swedish_label="Ett dokument per körning, jämför mot tidigare material",
                english_label="One document per run, compare against earlier saved material",
                swedish_description="Ladda upp ett dokument och jämför det mot tidigare sparat material.",
                english_description="Upload one document and compare it against previous material.",
                value="single_document_against_previous",
            ),
            _option(
                language=language,
                id="remove_direct_comparison",
                swedish_label="Ingen direkt jämförelse behövs",
                english_label="No direct comparison needed",
                swedish_description="Behåll en fil per körning och ta bort kravet på direkt jämförelse.",
                english_description="Keep one file per run and remove the comparison requirement.",
                value="remove_direct_comparison",
            ),
        ),
    )


def comparison_scope_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="comparison_scope",
        question=localized_text(
            language,
            "När ska flödet jämföra dokument?",
            "When should the flow compare documents?",
        ),
        options=(
            _option(
                language=language,
                id="same_run_compare",
                swedish_label="Jämför dokument i samma körning",
                english_label="Compare documents in the same run",
                swedish_description="Ladda upp flera dokument tillsammans och jämför dem direkt.",
                english_description="Upload several documents together and compare them directly.",
                value="same_run_compare",
            ),
            _option(
                language=language,
                id="compare_previous_material",
                swedish_label="Jämför mot tidigare sparat material",
                english_label="Compare against earlier saved material",
                swedish_description="Ladda upp ett dokument och jämför det mot tidigare material.",
                english_description="Upload one document and compare it to stored earlier material.",
                value="compare_previous_material",
            ),
            _option(
                language=language,
                id="no_direct_compare",
                swedish_label="Ingen direkt jämförelse behövs",
                english_label="No direct comparison needed",
                swedish_description="Analysera ett dokument i taget utan uttrycklig jämförelse.",
                english_description="Analyze one document at a time without explicit comparison.",
                value="no_direct_compare",
            ),
        ),
    )


def final_output_mode_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="final_output_mode",
        question=localized_text(
            language,
            "Vad ska flödet producera som slutresultat?",
            "What should the flow produce as the final output?",
        ),
        options=(
            _option(
                language=language,
                id="structured_text",
                swedish_label="Strukturerat beslutsunderlag som text",
                english_label="Structured decision support as text",
                swedish_description="Ett läsbart memo eller beslutsunderlag direkt i flödet.",
                english_description="A readable memo or decision-support text in the flow output.",
                value="structured_text",
            ),
            _option(
                language=language,
                id="pdf_document",
                swedish_label="PDF-dokument",
                english_label="PDF document",
                swedish_description="Generera en PDF som slutresultat.",
                english_description="Generate a PDF document as the final output.",
                value="pdf_document",
            ),
            _option(
                language=language,
                id="docx_document",
                swedish_label="DOCX-dokument",
                english_label="DOCX document",
                swedish_description="Generera ett Word-dokument som slutresultat.",
                english_description="Generate a Word document as the final output.",
                value="docx_document",
            ),
            _option(
                language=language,
                id="structured_json",
                swedish_label="Strukturerad JSON",
                english_label="Structured JSON",
                swedish_description="Maskinläsbara fält för vidare automation eller system.",
                english_description="Produce machine-readable fields for downstream systems.",
                value="structured_json",
            ),
        ),
    )


def docx_output_mode_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="docx_output_mode",
        question=localized_text(
            language,
            "Hur ska DOCX-resultatet skapas?",
            "How should the DOCX output be created?",
        ),
        options=(
            _option(
                language=language,
                id="generated_docx",
                swedish_label="Genererad DOCX utan mall",
                english_label="Generated DOCX without template",
                swedish_description="Skapa dokumentinnehållet direkt utan en fast mall.",
                english_description="Generate the document content directly without a fixed template.",
                value="generated_docx",
            ),
            _option(
                language=language,
                id="template_fill_docx",
                swedish_label="DOCX från mall",
                english_label="DOCX from template",
                swedish_description="Fyll en befintlig DOCX-mall med strukturerade fält.",
                english_description="Fill an existing DOCX template with structured fields.",
                value="template_fill_docx",
            ),
        ),
    )


def output_reader_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="output_reader",
        question=localized_text(
            language,
            "Vem är den huvudsakliga läsaren av slutresultatet?",
            "Who is the main reader of the final output?",
        ),
        options=(
            _option(
                language=language,
                id="manager_politician_reader",
                swedish_label="Chef eller politiker",
                english_label="Manager or politician",
                swedish_description="Använd en kort, tydlig och beslutsinriktad ton för ledning.",
                english_description="Use a concise and decision-oriented style for leaders.",
                value="manager_politician_reader",
            ),
            _option(
                language=language,
                id="case_officer_reader",
                swedish_label="Handläggare eller analytiker",
                english_label="Case officer or analyst",
                swedish_description="Använd en mer detaljerad och arbetsinriktad analysstil.",
                english_description="Use a more detailed working style for professional analysis.",
                value="case_officer_reader",
            ),
            _option(
                language=language,
                id="mixed_reader",
                swedish_label="Blandad målgrupp",
                english_label="Mixed audience",
                swedish_description="Balansera läsbarhet och analytisk detalj för flera typer av läsare.",
                english_description="Balance readability and analytical detail for different readers.",
                value="mixed_reader",
            ),
        ),
    )


def decision_support_scope_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="decision_support_scope",
        question=localized_text(
            language,
            "Vad ska beslutsunderlaget innehålla?",
            "What should the decision-support output include?",
        ),
        options=(
            _option(
                language=language,
                id="summary_only",
                swedish_label="Bara sammanfattning",
                english_label="Summary only",
                swedish_description="Håll slutresultatet kort och fokuserat på en överblick.",
                english_description="Keep the final output short and focused on a concise overview.",
                value="summary_only",
            ),
            _option(
                language=language,
                id="summary_and_assessment",
                swedish_label="Sammanfattning + bedömning",
                english_label="Summary + assessment",
                swedish_description="Kombinera en sammanfattning med analys och slutsatser.",
                english_description="Combine a case summary with analysis and conclusions.",
                value="summary_and_assessment",
            ),
            _option(
                language=language,
                id="summary_assessment_decision",
                swedish_label="Sammanfattning + bedömning + beslutsförslag",
                english_label="Summary + assessment + decision proposal",
                swedish_description="Inkludera också ett förslag till beslut eller rekommenderad åtgärd.",
                english_description="Include a proposed decision or recommendation for action.",
                value="summary_assessment_decision",
            ),
            _option(
                language=language,
                id="custom_sections",
                swedish_label="Specifika sektioner",
                english_label="Specific sections",
                swedish_description="Slutresultatet ska följa egna sektioner som användaren väljer.",
                english_description="The output should follow custom sections chosen by the user.",
                value="custom_sections",
            ),
        ),
    )


def runtime_metadata_fields_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="runtime_metadata_fields",
        question=localized_text(
            language,
            "Ska användaren också ange metadata vid körning?",
            "Should the user also enter metadata at runtime?",
        ),
        options=(
            _option(
                language=language,
                id="no_extra_metadata",
                swedish_label="Inga extra fält",
                english_label="No extra fields",
                swedish_description="Använd bara de uppladdade dokumenten som indata.",
                english_description="Use only the uploaded documents as input.",
                value="no_extra_metadata",
            ),
            _option(
                language=language,
                id="basic_case_metadata",
                swedish_label="Lägg till grundläggande metadata",
                english_label="Add basic metadata",
                swedish_description="Låt användaren ange några enkla återanvändbara fält.",
                english_description="Let the user enter a few simple reusable fields.",
                value="basic_case_metadata",
            ),
            _option(
                language=language,
                id="detailed_case_metadata",
                swedish_label="Lägg till rikare metadatafält",
                english_label="Add richer metadata fields",
                swedish_description="Samla flera återanvändbara fält som referenser, språk, fokus, datum eller ansvarig avdelning.",
                english_description="Collect several reusable inputs such as references, language, focus, dates, or responsible department.",
                value="detailed_case_metadata",
            ),
        ),
    )


def structured_analysis_need_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="structured_analysis_need",
        question=localized_text(
            language,
            "Ska flödet också ta fram strukturerad analys som kan återanvändas i senare steg?",
            "Should the flow also produce structured analysis that later steps can reuse?",
        ),
        options=(
            _option(
                language=language,
                id="use_structured_analysis",
                swedish_label="Ja, använd strukturerad analys där det förbättrar kvaliteten",
                english_label="Yes, use structured analysis where it improves quality",
                swedish_description="Extrahera viktiga fält som JSON innan slutrapporten skrivs.",
                english_description="Extract important fields as JSON before writing the final report.",
                value="use_structured_analysis",
            ),
            _option(
                language=language,
                id="text_only_analysis",
                swedish_label="Nej, håll analysen som vanlig text",
                english_label="No, keep the analysis as plain text",
                swedish_description="Undvik extra struktur om den inte behövs.",
                english_description="Avoid extra structure if it is not needed.",
                value="text_only_analysis",
            ),
        ),
    )


def final_pdf_type_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="final_pdf_type",
        question=localized_text(
            language,
            "Vilken typ av slut-PDF vill du ha?",
            "What kind of final PDF do you want?",
        ),
        options=(
            _option(
                language=language,
                id="summary_pdf",
                swedish_label="Kort sammanfattning med nyckelpunkter",
                english_label="Short summary with key points",
                swedish_description="En kompakt PDF med de viktigaste insikterna.",
                english_description="A compact PDF with the most important insights.",
                value="summary_pdf",
            ),
            _option(
                language=language,
                id="structured_report_pdf",
                swedish_label="Strukturerad rapport",
                english_label="Structured report",
                swedish_description="En rapport med tydliga rubriker, slutsatser och rekommendationer.",
                english_description="A report with clear sections, conclusions, and recommendations.",
                value="structured_report_pdf",
            ),
            _option(
                language=language,
                id="fact_list_pdf",
                swedish_label="Faktalista eller punktlista",
                english_label="Fact list or bullet summary",
                swedish_description="Främst extraherade fakta och detaljer utan längre analys.",
                english_description="Mainly extracted facts and details without extended analysis.",
                value="fact_list_pdf",
            ),
        ),
    )


def pdf_generation_mode_question(language: DiscoveryLanguage) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="pdf_generation_mode",
        question=localized_text(
            language,
            "När du säger PDF-mall, vilket upplägg menar du?",
            "When you say PDF template, which setup do you mean?",
        ),
        options=(
            _option(
                language=language,
                id="generated_pdf",
                swedish_label="Vanlig genererad PDF",
                english_label="Normal generated PDF",
                swedish_description="Skapa en PDF direkt från analysen utan en fast mall.",
                english_description="Generate a PDF directly from the analysis without a fixed template.",
                value="generated_pdf",
            ),
            _option(
                language=language,
                id="pdf_template_requested",
                swedish_label="Specifik PDF-mall krävs",
                english_label="A specific PDF template is required",
                swedish_description="Slutresultatet behöver följa en bestämd PDF-mall eller layout. Inbyggd mallfyllning stöds bara för DOCX/Word.",
                english_description="The final result must follow a specific PDF template or layout. Native template filling is only supported for DOCX/Word.",
                value="pdf_template_requested",
            ),
        ),
    )


def question_suggestion_for_id(
    question_id: str,
    *,
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion | None:
    builders: dict[str, Callable[[DiscoveryLanguage], DiscoveryQuestionSuggestion]] = {
        "processing_scope": processing_scope_question,
        "input_material_mode": input_material_mode_question,
        "flow_input_architecture": flow_input_architecture_question,
        "document_kind": document_kind_question,
        "document_material_scope": document_material_scope_question,
        "comparison_scope": comparison_scope_question,
        "final_output_mode": final_output_mode_question,
        "docx_output_mode": docx_output_mode_question,
        "output_reader": output_reader_question,
        "decision_support_scope": decision_support_scope_question,
        "runtime_metadata_fields": runtime_metadata_fields_question,
        "structured_analysis_need": structured_analysis_need_question,
        "final_pdf_type": final_pdf_type_question,
        "pdf_generation_mode": pdf_generation_mode_question,
    }
    builder = builders.get(question_id)
    if builder is None:
        return None
    return builder(language)
