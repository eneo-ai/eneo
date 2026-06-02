from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

QUESTION_ID_ALIASES: dict[str, str] = {
    "final_output_format": "final_output_mode",
    "primary_output_format": "final_output_mode",
    "output_format": "final_output_mode",
    "file_handling_mode": "document_material_scope",
    "upload_mode": "document_material_scope",
    "final_output_type": "final_output_mode",
}

OPTION_ID_ALIASES: dict[str, dict[str, str]] = {
    "final_output_mode": {
        "text_output": "structured_text",
        "text_brief": "structured_text",
        "structured_text": "structured_text",
        "docx_generated": "docx_document",
        "docx_output": "docx_document",
        "docx_document": "docx_document",
        "docx_template": "docx_document",
        "json_output": "structured_json",
        "structured_json": "structured_json",
        "json_analysis_plus_text": "structured_json",
        "pdf_output": "pdf_document",
        "final_pdf": "pdf_document",
        "pdf_document": "pdf_document",
        "comparison_report_text": "structured_text",
        "executive_summary": "structured_text",
        "comparison_matrix_json": "structured_json",
        "docx_report": "docx_document",
    },
    "document_material_scope": {
        "multi_upload_same_run": "multiple_documents_case",
        "multiple_same_run": "multiple_documents_case",
        "single_file_per_run": "single_document_case",
        "one_per_run": "single_document_case",
    },
    "runtime_metadata_fields": {
        "add_basic_metadata": "basic_case_metadata",
    },
}

SUPPORTED_STRUCTURED_QUESTION_IDS: frozenset[str] = frozenset(
    {
        "processing_scope",
        "input_material_mode",
        "flow_input_architecture",
        "document_kind",
        "document_material_scope",
        "post_processing_goal",
        "structured_io_contract",
        "comparison_scope",
        "final_output_mode",
        "docx_output_mode",
        "output_reader",
        "final_output_scope",
        "runtime_metadata_fields",
        "structured_analysis_need",
        "output_style",
        "output_tone",
        "detail_level",
        "final_pdf_type",
        "pdf_generation_mode",
    }
)


def canonical_question_id(question_id: str) -> str:
    return QUESTION_ID_ALIASES.get(question_id, question_id)


def canonical_option_id(question_id: str, option_id: str) -> str:
    canonical_question = canonical_question_id(question_id)
    return OPTION_ID_ALIASES.get(canonical_question, {}).get(option_id, option_id)


def normalize_structured_question_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_question_id = normalized.get("question_id")
    if isinstance(raw_question_id, str) and raw_question_id:
        normalized_question_id = canonical_question_id(raw_question_id)
        normalized["question_id"] = normalized_question_id

        raw_options = normalized.get("options")
        if isinstance(raw_options, list):
            normalized_options: list[object] = []
            for option in cast(list[object], raw_options):
                if not isinstance(option, Mapping):
                    normalized_options.append(option)
                    continue
                option_map = cast(Mapping[str, Any], option)
                normalized_option: dict[str, Any] = dict(option_map)
                option_id = normalized_option.get("id")
                if isinstance(option_id, str) and option_id:
                    normalized_option["id"] = canonical_option_id(
                        normalized_question_id,
                        option_id,
                    )
                value = normalized_option.get("value")
                if isinstance(value, str) and value:
                    normalized_option["value"] = canonical_option_id(
                        normalized_question_id,
                        value,
                    )
                normalized_options.append(normalized_option)
            normalized["options"] = normalized_options
    return normalized


def normalize_question_answer(answer: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(answer)
    raw_question_id = normalized.get("question_id")
    if not isinstance(raw_question_id, str) or not raw_question_id:
        return normalized

    normalized_question_id = canonical_question_id(raw_question_id)
    normalized["question_id"] = normalized_question_id

    for key in ("selected_option_ids", "selected_values"):
        raw_values = normalized.get(key)
        if not isinstance(raw_values, list):
            continue
        normalized[key] = [
            canonical_option_id(normalized_question_id, value)
            if isinstance(value, str)
            else value
            for value in cast(list[object], raw_values)
        ]

    answer_value = normalized.get("answer")
    if isinstance(answer_value, str) and answer_value:
        normalized["answer"] = canonical_option_id(normalized_question_id, answer_value)

    custom_value = normalized.get("custom_value")
    if isinstance(custom_value, str) and custom_value:
        normalized["custom_value"] = canonical_option_id(
            normalized_question_id,
            custom_value,
        )

    for singular_key in ("selected_option_id", "selected_value"):
        raw_value = normalized.get(singular_key)
        if isinstance(raw_value, str) and raw_value:
            normalized[singular_key] = canonical_option_id(
                normalized_question_id,
                raw_value,
            )

    return normalized


def is_supported_structured_question_id(question_id: str) -> bool:
    return canonical_question_id(question_id) in SUPPORTED_STRUCTURED_QUESTION_IDS


def supported_structured_question_ids() -> tuple[str, ...]:
    return tuple(sorted(SUPPORTED_STRUCTURED_QUESTION_IDS))
