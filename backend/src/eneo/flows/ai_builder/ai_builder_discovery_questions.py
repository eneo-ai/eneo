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
                example=option.example,
            )
            for option in rendered.options
        ),
        exposure=template.exposure,
        allow_custom=rendered.allow_custom,
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
            "I en körning kan flödet antingen transkribera ljud eller läsa uppladdade dokument, inte båda. Vad ska det ta emot?",
            "In one run the flow can either transcribe a recording or read uploaded documents, not both. Which should it accept?",
        ),
        options=(
            _option(
                language=language,
                id="document_primary_input",
                swedish_label="Dokumenten",
                english_label="The documents",
                swedish_description="Flödet läser de uppladdade dokumenten. Ljudet transkriberas då inte i flödet.",
                english_description="The flow reads the uploaded documents. The recording is then not transcribed in the flow.",
                value="document_primary_input",
            ),
            _option(
                language=language,
                id="audio_primary_input",
                swedish_label="Ljudet",
                english_label="The recording",
                swedish_description="Flödet transkriberar ljudet. Dokumenten laddas då inte upp i samma körning.",
                english_description="The flow transcribes the recording. The documents are then not uploaded in the same run.",
                value="audio_primary_input",
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
    base = _catalog_question("comparison_scope", language=language)
    return DiscoveryQuestionSuggestion(
        question_id=base.question_id,
        question=localized_text(
            language,
            "Du valde en fil per körning men vill också jämföra dokument. Vilken jämförelsearkitektur vill du ha?",
            "You chose one file per run but also want document comparison. Which comparison architecture do you want?",
        ),
        options=base.options,
        selection_mode=base.selection_mode,
        allow_custom=base.allow_custom,
        exposure=base.exposure,
    )


def comparison_scope_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("comparison_scope", language=language)


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


def runtime_metadata_fields_question(
    language: DiscoveryLanguage,
) -> DiscoveryQuestionSuggestion:
    return _catalog_question("runtime_metadata_fields", language=language)


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
        "primary_runtime_input": primary_runtime_input_question,
        "flow_input_architecture": flow_input_architecture_question,
        "document_material_scope": document_material_scope_question,
        "report_disposition": report_disposition_question,
        "post_processing_goal": post_processing_goal_question,
        "structured_io_contract": structured_io_contract_question,
        "comparison_scope": comparison_scope_question,
        "terminal_output": terminal_output_question,
        "docx_output_mode": docx_output_mode_question,
        "runtime_metadata_fields": runtime_metadata_fields_question,
        "mapped_file_limit": mapped_file_limit_question,
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
