from __future__ import annotations

from collections.abc import Callable

from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryLanguage,
    DiscoveryQuestionOption,
    DiscoveryQuestionSuggestion,
    QuestionExposure,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    render_question,
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


def _catalog_question(
    slot_name: str,
    *,
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    template = QUESTION_CATALOG[slot_name]
    rendered = render_question(slot_name, language)
    return DiscoveryQuestionSuggestion(
        question_id=slot_name,
        question=rendered.question,
        options=tuple(
            DiscoveryQuestionOption(
                id=option.id,
                label=option.label,
                description=option.description,
                value=option.value,
            )
            for option in rendered.options
        ),
        exposure=template.exposure,
    )


def processing_scope_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
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
                swedish_label="Ett paket åt gången",
                english_label="One package at a time",
                swedish_description="Varje körning behandlar ett huvudpaket, avtal eller materialpaket i taget.",
                english_description="Each run processes one main package, contract, or source bundle at a time.",
                value="single_case",
            ),
            _option(
                language=language,
                id="multiple_cases",
                swedish_label="Flera paket i samma körning",
                english_label="Multiple packages in one run",
                swedish_description="En körning ska kunna hantera flera separata paket eller materialgrupper tillsammans.",
                english_description="One run should handle several separate packages or source bundles together.",
                value="multiple_cases",
            ),
        ),
    )


def primary_runtime_input_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("primary_runtime_input", language=language)


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
                swedish_label="Rapporter och formella dokument",
                english_label="Reports and formal documents",
                swedish_description="Rapporter, beslut, memon och annat formellt underlag.",
                english_description="Reports, decisions, memos, and other formal source material.",
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


def document_material_scope_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("document_material_scope", language=language)


def report_disposition_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("report_disposition", language=language)


def post_processing_goal_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("post_processing_goal", language=language)


def structured_io_contract_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("structured_io_contract", language=language)


def mapped_file_limit_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("mapped_file_limit", language=language)


def comparison_scope_conflict_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
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


def comparison_scope_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
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


def terminal_output_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("terminal_output", language=language)


def external_delivery_internal_output_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    base = terminal_output_question(language)
    return DiscoveryQuestionSuggestion(
        question_id=base.question_id,
        question=localized_text(
            language,
            "AI Builder kan inte skapa ett utgående API-leveranssteg automatiskt ännu. Vilket internt resultat ska flödet skapa för vidare hantering?",
            "AI Builder cannot automatically create an outbound API delivery step yet. What internal result should the flow create for downstream handling?",
        ),
        options=base.options,
        selection_mode=base.selection_mode,
        allow_custom=base.allow_custom,
        exposure=base.exposure,
    )


def docx_output_mode_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("docx_output_mode", language=language)


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
                id="specialist_reader",
                swedish_label="Specialist eller analytiker",
                english_label="Specialist or analyst",
                swedish_description="Använd en mer detaljerad och arbetsinriktad analysstil.",
                english_description="Use a more detailed working style for professional analysis.",
                value="specialist_reader",
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


def final_output_scope_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return DiscoveryQuestionSuggestion(
        question_id="final_output_scope",
        question=localized_text(
            language,
            "Hur detaljerat ska slutresultatet vara?",
            "How detailed should the final output be?",
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
                swedish_label="Sammanfattning + analys",
                english_label="Summary + analysis",
                swedish_description="Kombinera en sammanfattning med analys och slutsatser.",
                english_description="Combine a summary with analysis and conclusions.",
                value="summary_and_assessment",
            ),
            _option(
                language=language,
                id="summary_assessment_recommendation",
                swedish_label="Sammanfattning + analys + rekommendation",
                english_label="Summary + analysis + recommendation",
                swedish_description="Inkludera också en rekommendation eller förslag på nästa steg.",
                english_description="Include a recommendation or next-step proposal.",
                value="summary_assessment_recommendation",
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


def runtime_metadata_fields_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("runtime_metadata_fields", language=language)


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


def pdf_generation_mode_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("pdf_generation_mode", language=language)


def question_suggestion_for_id(
    question_id: str,
    *,
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion | None:
    builders: dict[str, Callable[[DiscoveryLanguage], DiscoveryQuestionSuggestion]] = {
        "processing_scope": processing_scope_question,
        "primary_runtime_input": primary_runtime_input_question,
        "flow_input_architecture": flow_input_architecture_question,
        "document_kind": document_kind_question,
        "document_material_scope": document_material_scope_question,
        "report_disposition": report_disposition_question,
        "post_processing_goal": post_processing_goal_question,
        "structured_io_contract": structured_io_contract_question,
        "comparison_scope": comparison_scope_question,
        "terminal_output": terminal_output_question,
        "docx_output_mode": docx_output_mode_question,
        "output_reader": output_reader_question,
        "final_output_scope": final_output_scope_question,
        "runtime_metadata_fields": runtime_metadata_fields_question,
        "mapped_file_limit": mapped_file_limit_question,
        "final_pdf_type": final_pdf_type_question,
        "pdf_generation_mode": pdf_generation_mode_question,
    }
    builder = builders.get(canonical_question_id(question_id))
    if builder is None:
        return None
    return builder(language)


def question_exposure_for_id(question_id: str) -> QuestionExposure:
    suggestion = question_suggestion_for_id(question_id, language="sv")
    if suggestion is None:
        return "user_requirement"
    return suggestion.exposure
