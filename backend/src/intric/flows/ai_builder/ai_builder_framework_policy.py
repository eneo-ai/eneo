from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
)
from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
    normalize_signal_text,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage, OutputType
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)

OUTPUT_CHANGE_KEYWORDS: tuple[str, ...] = (
    "structured json",
    "structured_text",
    "structured text",
    "slut-pdf",
    "final pdf",
    "pdf-dokument",
    "pdf document",
    "docx-dokument",
    "docx document",
    "text summary",
    "textsammanfattning",
)

RUNTIME_METADATA_KEYWORDS: tuple[str, ...] = (
    "ärendenummer",
    "case number",
    "committee",
    "nämnd",
    "språk",
    "language",
    "fokus",
    "focus",
    "metadata",
    "form fields",
    "formulärfält",
)

STRUCTURED_EXTRACTION_KEYWORDS: tuple[str, ...] = (
    "structured data",
    "strukturerad data",
    "json",
    "output contract",
    "output_contract",
    "extrahera viktiga fakta",
    "risker",
    "möjligheter",
    "rekommendationer",
    "key facts",
    "risks",
    "opportunities",
    "recommendations",
)

DOCX_TEMPLATE_MODE_MARKERS: tuple[str, ...] = (
    "template fill",
    "template_fill",
    "template",
    "mall",
    "fylla i",
)

DOCX_GENERATED_MODE_MARKERS: tuple[str, ...] = (
    "utan mall",
    "without template",
)

DOCX_CONTEXT_MARKERS: tuple[str, ...] = (
    "docx",
    "word",
    "word-dokument",
    "word document",
)

PDF_TEMPLATE_EXPECTATION_MARKERS: tuple[str, ...] = (
    "pdf mall",
    "pdf-mall",
    "pdf template",
    "pdf-template",
    "template pdf",
    "fillable pdf",
    "fixed pdf layout",
    "fast pdf layout",
    "specific pdf layout",
    "specifik pdf layout",
)

PDF_TEMPLATE_GENERIC_MARKERS: tuple[str, ...] = (
    "mall",
    "template",
    "fylla i",
    "fyll i",
    "fixed layout",
    "fast layout",
    "specific layout",
    "specifik layout",
)

PDF_GENERATED_MODE_MARKERS: tuple[str, ...] = (
    "generated pdf",
    "vanlig pdf",
    "normal pdf",
    "utan mall",
    "without template",
)

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
        "comparison_scope",
        "final_output_mode",
        "docx_output_mode",
        "output_reader",
        "decision_support_scope",
        "runtime_metadata_fields",
        "structured_analysis_need",
        "output_style",
        "output_tone",
        "detail_level",
        "final_pdf_type",
        "pdf_generation_mode",
    }
)


@dataclass(frozen=True, slots=True)
class OutputIntentResolution:
    terminal_output: str | None
    content_shape: str | None = None
    docx_output_mode: str | None = None
    pdf_generation_mode: str | None = None

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
            normalized_options: list[dict[str, Any]] = []
            for option in raw_options:
                if not isinstance(option, Mapping):
                    normalized_options.append(option)
                    continue
                normalized_option = dict(option)
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
            canonical_option_id(normalized_question_id, value) if isinstance(value, str) else value
            for value in raw_values
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


def latest_pending_structured_question(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(conversation):
        role = message.role if isinstance(message, ConversationMessage) else message.get("role")
        tool_calls = (
            message.tool_calls
            if isinstance(message, ConversationMessage)
            else message.get("tool_calls")
        )
        if role != "assistant" or not isinstance(tool_calls, Sequence):
            continue
        for tool_call in reversed(tool_calls):
            if not isinstance(tool_call, Mapping):
                continue
            if tool_call.get("name") != "ask_structured_question":
                continue
            arguments = tool_call.get("arguments")
            payload = arguments
            if isinstance(arguments, str):
                try:
                    payload = json.loads(arguments)
                except json.JSONDecodeError:
                    payload = None
            if not isinstance(payload, Mapping):
                continue
            normalized = normalize_structured_question_payload(payload)
            question_id = normalized.get("question_id")
            if isinstance(question_id, str) and question_id:
                return normalized
    return None


def has_explicit_structured_answer(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    question_id: str,
) -> bool:
    canonical_id = canonical_question_id(question_id)
    for message in conversation:
        role = message.role if isinstance(message, ConversationMessage) else message.get("role")
        metadata = (
            message.metadata
            if isinstance(message, ConversationMessage)
            else message.get("metadata")
        )
        if role != "user" or not isinstance(metadata, Mapping):
            continue
        answer = metadata.get("question_answer")
        if not isinstance(answer, Mapping):
            continue
        normalized = normalize_question_answer(answer)
        answer_question_id = normalized.get("question_id")
        if isinstance(answer_question_id, str) and canonical_question_id(answer_question_id) == canonical_id:
            return True
    return False


def infer_question_answer_from_freeform(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    message: str,
) -> dict[str, Any] | None:
    question = latest_pending_structured_question(conversation)
    if question is None:
        return None

    question_id = question.get("question_id")
    options = question.get("options")
    if not isinstance(question_id, str) or not isinstance(options, list):
        return None

    inferred_values = infer_answer_signals_from_text(message).get(question_id, set())
    if len(inferred_values) == 1:
        inferred_value = next(iter(inferred_values))
        return normalize_question_answer(
            {
                "question_id": question_id,
                "selected_option_id": inferred_value,
                "selected_value": inferred_value,
                "answer": inferred_value,
            }
        )

    normalized_message = normalize_signal_text(message)
    if not normalized_message:
        return None

    best_option: dict[str, Any] | None = None
    best_score = 0.0
    tie = False
    for option in options:
        if not isinstance(option, Mapping):
            continue
        score = _score_option_match(normalized_message, option)
        if score > best_score:
            best_option = dict(option)
            best_score = score
            tie = False
        elif score > 0 and abs(score - best_score) < 1e-6:
            tie = True

    if best_option is None or best_score < 0.45 or tie:
        return None

    option_id = best_option.get("id")
    option_value = best_option.get("value")
    selected = option_id if isinstance(option_id, str) and option_id else option_value
    if not isinstance(selected, str) or not selected:
        return None

    return normalize_question_answer(
        {
            "question_id": question_id,
            "selected_option_id": selected,
            "selected_value": selected,
            "answer": selected,
        }
    )


def aggregate_user_text(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> str:
    return _aggregate_user_text(conversation, include_structured_answers=True)


def aggregate_freeform_user_text(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> str:
    return _aggregate_user_text(conversation, include_structured_answers=False)


def _aggregate_user_text(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    *,
    include_structured_answers: bool,
) -> str:
    parts: list[str] = []
    for message in conversation:
        role = message.role if isinstance(message, ConversationMessage) else message.get("role")
        content = (
            message.content
            if isinstance(message, ConversationMessage)
            else message.get("content")
        )
        metadata = (
            message.metadata
            if isinstance(message, ConversationMessage)
            else message.get("metadata")
        )
        if role != "user" or not isinstance(content, str):
            continue
        if not include_structured_answers and isinstance(metadata, Mapping):
            question_answer = metadata.get("question_answer")
            if isinstance(question_answer, Mapping) and _looks_like_structured_answer_echo(
                content,
                question_answer,
            ):
                continue
        parts.append(content.casefold())
    return "\n".join(parts)


def _looks_like_structured_answer_echo(
    content: str,
    question_answer: Mapping[str, Any],
) -> bool:
    normalized_content = content.casefold().strip()
    if not normalized_content:
        return True

    candidates: set[str] = set()
    for key in (
        "selected_option_id",
        "selected_value",
        "answer",
        "custom_value",
    ):
        raw_value = question_answer.get(key)
        if isinstance(raw_value, str) and raw_value:
            candidates.add(raw_value.casefold())
    for key in ("selected_option_ids", "selected_values"):
        raw_values = question_answer.get(key)
        if not isinstance(raw_values, Sequence):
            continue
        for raw_value in raw_values:
            if isinstance(raw_value, str) and raw_value:
                candidates.add(raw_value.casefold())

    if normalized_content in candidates:
        return True

    return len(normalized_content) <= 80 and not any(
        marker in normalized_content for marker in (".", "?", "!", "\n")
    )


def _score_option_match(message: str, option: Mapping[str, Any]) -> float:
    candidates = [
        option.get("label"),
        option.get("description"),
        option.get("value"),
        option.get("id"),
    ]
    normalized_candidates = [
        normalize_signal_text(candidate)
        for candidate in candidates
        if isinstance(candidate, str) and candidate.strip()
    ]
    if not normalized_candidates:
        return 0.0

    if any(message == candidate for candidate in normalized_candidates):
        return 1.0
    if any(candidate in message or message in candidate for candidate in normalized_candidates):
        return 0.8

    message_tokens = set(message.split())
    best = 0.0
    for candidate in normalized_candidates:
        candidate_tokens = set(candidate.split())
        if not candidate_tokens:
            continue
        overlap = len(message_tokens & candidate_tokens)
        if overlap < 2:
            continue
        ratio = overlap / max(1, min(len(message_tokens), len(candidate_tokens)))
        best = max(best, ratio)
    return best


def extract_answer_signals(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> dict[str, set[str]]:
    """Extract effective answer signals with latest-turn precedence per question.

    Freeform inference and structured answers are both read from the conversation,
    but newer turns replace older values for the same question family instead of
    accumulating a bag of stale signals across the whole session.
    """
    signals: dict[str, set[str]] = {}
    for message in conversation:
        role = message.role if isinstance(message, ConversationMessage) else message.get("role")
        metadata = (
            message.metadata
            if isinstance(message, ConversationMessage)
            else message.get("metadata")
        )
        content = (
            message.content
            if isinstance(message, ConversationMessage)
            else message.get("content")
        )
        if role != "user":
            continue

        answer = metadata.get("question_answer") if isinstance(metadata, dict) else None

        if (
            isinstance(content, str)
            and content.strip()
            and not isinstance(answer, dict)
        ):
            inferred_signals = infer_answer_signals_from_text(content)
            for inferred_question_id, inferred_values in inferred_signals.items():
                if inferred_question_id == "comparison_scope":
                    continue
                signals[inferred_question_id] = set(inferred_values)

        if not isinstance(metadata, dict):
            continue

        if not isinstance(answer, dict):
            continue
        answer = normalize_question_answer(answer)
        question_id = answer.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            continue

        values: set[str] = set()
        for raw_values in (answer.get("selected_option_ids"), answer.get("selected_values")):
            if not isinstance(raw_values, list):
                continue
            for value in raw_values:
                if isinstance(value, str) and value:
                    values.add(value.casefold())
                elif value is not None:
                    values.add(str(value).casefold())
        for raw_value in (
            answer.get("selected_option_id"),
            answer.get("selected_value"),
            answer.get("answer"),
        ):
            if isinstance(raw_value, str) and raw_value:
                values.add(raw_value.casefold())
        custom_value = answer.get("custom_value")
        if isinstance(custom_value, str) and custom_value:
            values.add(custom_value.casefold())
        if isinstance(content, str) and content.strip():
            values.add(content.casefold())
        signals[question_id] = values
    return signals


def question_is_already_resolved(
    question_id: str,
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    *,
    flow=None,
) -> bool:
    canonical_id = canonical_question_id(question_id)
    answer_signals = extract_answer_signals(conversation)
    freeform_text = aggregate_freeform_user_text(conversation)
    flow_defaults = build_flow_discovery_defaults(flow)

    if canonical_id == "final_output_mode":
        return (
            resolve_explicit_output_choice(
                freeform_text,
                answer_signals,
                flow_defaults=flow_defaults,
            )
            is not None
        )

    if canonical_id == "docx_output_mode":
        values = answer_signals.get("docx_output_mode", set())
        if values:
            return True
        return bool(flow_defaults.get("docx_output_mode")) and not mentions_output_change(
            freeform_text
        )

    values = answer_signals.get(canonical_id, set())
    if values:
        return True

    return bool(flow_defaults.get(canonical_id)) and not mentions_output_change(
        freeform_text
    )


def is_supported_structured_question_id(question_id: str) -> bool:
    return canonical_question_id(question_id) in SUPPORTED_STRUCTURED_QUESTION_IDS


def supported_structured_question_ids() -> tuple[str, ...]:
    return tuple(sorted(SUPPORTED_STRUCTURED_QUESTION_IDS))


def resolve_explicit_output_choice(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    flow_defaults: dict[str, set[str]] | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    output_values = answer_signals.get("final_output_mode", set())
    pdf_generation_values = answer_signals.get("pdf_generation_mode", set())
    if (
        "pdf_document" in output_values
        or pdf_generation_values.intersection({"generated_pdf", "pdf_template_requested"})
        or contains_any_phrase(
            normalized_text,
            ("slut pdf", "final pdf", "ny pdf", "en pdf", "pdf med"),
        )
    ):
        return "pdf_document"
    if contains_any_phrase(
        normalized_text,
        (
            "beslutsunderlag som text",
            "structured decision support as text",
            "decision support as text",
            "decision support text",
            "decision-support text",
            "text summary",
            "textsammanfattning",
            "sammanfattning som text",
        ),
    ):
        return "structured_text"
    if "docx_document" in output_values or contains_any_phrase(normalized_text, ("docx",)):
        return "docx_document"
    if "structured_json" in output_values:
        return "structured_json"
    if "structured_text" in output_values:
        return "structured_text"

    if flow_defaults and "final_output_mode" in flow_defaults and not mentions_output_change(
        normalized_text
    ):
        defaults = flow_defaults["final_output_mode"]
        return next(iter(defaults)) if defaults else None

    if _looks_like_text_analysis_output(normalized_text):
        return "structured_text"
    if _infer_output_content_shape(normalized_text) == "structured_report":
        return "structured_text"

    return None


def resolve_docx_output_mode(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    explicit_output: str | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    resolved_output = explicit_output or resolve_explicit_output_choice(
        normalized_text,
        answer_signals,
    )
    if resolved_output != "docx_document":
        return None

    docx_mode_values = answer_signals.get("docx_output_mode", set())
    if "template_fill_docx" in docx_mode_values:
        return "template_fill_docx"
    if "generated_docx" in docx_mode_values:
        return "generated_docx"

    has_docx_context = contains_any_phrase(normalized_text, DOCX_CONTEXT_MARKERS)
    if not has_docx_context:
        return None

    if contains_any_phrase(normalized_text, DOCX_GENERATED_MODE_MARKERS):
        return "generated_docx"
    if contains_any_phrase(normalized_text, DOCX_TEMPLATE_MODE_MARKERS):
        return "template_fill_docx"
    return None


def resolve_pdf_generation_mode(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    explicit_output: str | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    resolved_output = explicit_output or resolve_explicit_output_choice(
        normalized_text,
        answer_signals,
    )
    if resolved_output != "pdf_document":
        return None

    pdf_mode_values = answer_signals.get("pdf_generation_mode", set())
    if "pdf_template_requested" in pdf_mode_values:
        return "pdf_template_requested"
    if "generated_pdf" in pdf_mode_values:
        return "generated_pdf"

    if contains_any_phrase(normalized_text, PDF_GENERATED_MODE_MARKERS):
        return "generated_pdf"
    if _looks_like_pdf_template_expectation(normalized_text):
        return "pdf_template_requested"
    return None


def resolve_output_intent(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    flow_defaults: dict[str, set[str]] | None = None,
) -> OutputIntentResolution:
    normalized_text = normalize_signal_text(text)
    content_shape = _infer_output_content_shape(normalized_text)
    terminal_output = resolve_explicit_output_choice(
        normalized_text,
        answer_signals,
        flow_defaults=flow_defaults,
    )
    return OutputIntentResolution(
        terminal_output=terminal_output,
        content_shape=content_shape,
        docx_output_mode=resolve_docx_output_mode(
            normalized_text,
            answer_signals,
            explicit_output=terminal_output,
        ),
        pdf_generation_mode=resolve_pdf_generation_mode(
            normalized_text,
            answer_signals,
            explicit_output=terminal_output,
        ),
    )


def _looks_like_text_analysis_output(text: str) -> bool:
    if contains_any_phrase(
        text,
        (
            "docx",
            "word",
            "rapport",
            "report",
            "memo",
            "sammanfattning",
            "summary",
            "json",
            "skapa en pdf",
            "create a pdf",
            "generate a pdf",
            "pdf-rapport",
            "slut-pdf",
            "final pdf",
        ),
    ):
        return False

    extraction_markers = (
        "extraherar",
        "extract",
        "structured data",
        "strukturerad data",
        "risker",
        "risks",
    )
    decision_markers = (
        "rekommenderad nästa åtgärd",
        "recommended next action",
        "rekommendation",
        "recommendation",
        "assessment",
        "bedömning",
    )
    return contains_any_phrase(text, extraction_markers) and contains_any_phrase(
        text,
        decision_markers,
    )


def _looks_like_pdf_template_expectation(text: str) -> bool:
    if not contains_any_phrase(text, ("pdf",)):
        return False
    if contains_any_phrase(text, PDF_TEMPLATE_EXPECTATION_MARKERS):
        return True
    return contains_any_phrase(text, PDF_TEMPLATE_GENERIC_MARKERS)


def _infer_output_content_shape(text: str) -> str | None:
    report_markers = (
        "strukturerad rapport",
        "structured report",
        "rapport",
        "report",
        "beslutsunderlag",
        "memo",
        "sammanfattning",
        "summary",
    )
    structured_field_markers = (
        "keywords",
        "nyckelord",
        "namn",
        "datum",
        "ämne",
        "amne",
        "topic",
        "subject",
    )
    if contains_any_phrase(text, report_markers):
        return "structured_report"
    if contains_any_phrase(text, structured_field_markers) and contains_any_phrase(
        text,
        ("sammanfatta", "summarize", "transkribera", "transcribe"),
    ):
        return "structured_report"
    return None


def mentions_output_change(text: str) -> bool:
    normalized_text = text.casefold()
    return any(keyword in normalized_text for keyword in OUTPUT_CHANGE_KEYWORDS)


def mentions_runtime_metadata(text: str) -> bool:
    normalized_text = text.casefold()
    return any(keyword in normalized_text for keyword in RUNTIME_METADATA_KEYWORDS)


def runtime_metadata_requested(answer_signals: dict[str, set[str]]) -> bool:
    values = answer_signals.get("runtime_metadata_fields", set())
    return any(value in {"basic_case_metadata", "detailed_case_metadata"} for value in values)


def needs_structured_extraction(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    step_count: int,
    terminal_output_type: OutputType,
) -> bool:
    if step_count < 2:
        return False

    if "structured_json" in answer_signals.get("final_output_mode", set()):
        return False

    if terminal_output_type not in {OutputType.TEXT, OutputType.DOCX, OutputType.PDF}:
        return False

    return any(phrase in text for phrase in STRUCTURED_EXTRACTION_KEYWORDS)


def build_framework_guardrails_block() -> str:
    return """\
## Eneo Flow-ramverket

- Du får endast bygga giltiga Eneo-flöden med de tillåtna byggblocken i Flow-specen.
- Föreslå aldrig Python-kod, shell-script, egna mikrotjänster, egna integrationer eller annan specialexekvering utanför Eneos Flow-ramverk.
- Om användarens behov kräver något som inte kan uttryckas som ett Eneo-flöde ska du hålla dig inom Flow-specen, beskriva begränsningen kort och använda `manual_setup_notes` för sådant som måste kopplas manuellt.
- Alla planer måste uttryckas som steg, formulärfält, kontrakt, runtime-inputs, mallstrategier och andra stödda Flow-primitiver — inte som fri kod eller egen orkestreringslogik.
"""
