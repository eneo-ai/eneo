from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_canonicalization import (
    canonical_option_id,
    canonical_question_id,
    is_supported_structured_question_id,
    normalize_question_answer,
    normalize_structured_question_payload,
    supported_structured_question_ids,
)
from intric.flows.ai_builder.ai_builder_clause_segmenter import (
    RoleScopedText,
    build_role_scoped_text,
)
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_discovery_defaults,
)
from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
    normalize_signal_text,
)
from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_phrase,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_keywords import (
    DOCX_CONTEXT_MARKERS,
    DOCX_GENERATED_MODE_MARKERS,
    DOCX_TEMPLATE_MODE_MARKERS,
    OUTPUT_CHANGE_KEYWORDS,
    PDF_GENERATED_MODE_MARKERS,
    PDF_OUTPUT_CONTEXT_MARKERS,
    PDF_TEMPLATE_EXPECTATION_MARKERS,
    PDF_TEMPLATE_GENERIC_MARKERS,
    STRUCTURED_EXTRACTION_KEYWORDS,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage, OutputType
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    infer_runtime_metadata_slot,
)
from intric.flows.domain.flow import Flow, JsonObject

__all__ = [
    "aggregate_freeform_user_text",
    "aggregate_user_text",
    "build_framework_guardrails_block",
    "canonical_option_id",
    "canonical_question_id",
    "extract_freeform_user_messages",
    "extract_answer_signals",
    "infer_question_answer_from_freeform",
    "is_supported_structured_question_id",
    "latest_pending_structured_question",
    "mentions_output_change",
    "mentions_runtime_metadata",
    "needs_structured_extraction",
    "normalize_question_answer",
    "normalize_structured_question_payload",
    "question_is_already_resolved",
    "has_explicit_docx_mode_text",
    "has_explicit_pdf_mode_text",
    "resolve_docx_output_mode",
    "resolve_explicit_output_choice",
    "resolve_output_intent",
    "runtime_metadata_requested",
    "supported_structured_question_ids",
]


@dataclass(frozen=True, slots=True)
class OutputIntentResolution:
    terminal_output: str | None
    content_shape: str | None = None
    docx_output_mode: str | None = None
    pdf_generation_mode: str | None = None


def latest_pending_structured_question(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(conversation):
        role = (
            message.role
            if isinstance(message, ConversationMessage)
            else message.get("role")
        )
        tool_calls = (
            message.tool_calls
            if isinstance(message, ConversationMessage)
            else message.get("tool_calls")
        )
        if role != "assistant" or not isinstance(tool_calls, Sequence):
            continue
        for tool_call in reversed(cast(Sequence[object], tool_calls)):
            if not isinstance(tool_call, Mapping):
                continue
            tool_call_map = cast(Mapping[str, Any], tool_call)
            if tool_call_map.get("name") != "ask_structured_question":
                continue
            arguments = tool_call_map.get("arguments")
            payload = arguments
            if isinstance(arguments, str):
                try:
                    payload = json.loads(arguments)
                except json.JSONDecodeError:
                    payload = None
            if not isinstance(payload, Mapping):
                continue
            normalized = normalize_structured_question_payload(
                cast(Mapping[str, Any], payload)
            )
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
        role = (
            message.role
            if isinstance(message, ConversationMessage)
            else message.get("role")
        )
        metadata = (
            message.metadata
            if isinstance(message, ConversationMessage)
            else message.get("metadata")
        )
        if role != "user" or not isinstance(metadata, Mapping):
            continue
        metadata_map = cast(Mapping[str, Any], metadata)
        answer = metadata_map.get("question_answer")
        if not isinstance(answer, Mapping):
            continue
        normalized = normalize_question_answer(cast(Mapping[str, Any], answer))
        answer_question_id = normalized.get("question_id")
        if (
            isinstance(answer_question_id, str)
            and canonical_question_id(answer_question_id) == canonical_id
        ):
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
    for option in cast(list[object], options):
        if not isinstance(option, Mapping):
            continue
        option_map = cast(Mapping[str, Any], option)
        score = _score_option_match(normalized_message, option_map)
        if score > best_score:
            best_option = dict(option_map)
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


def extract_freeform_user_messages(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> list[tuple[int, str]]:
    messages: list[tuple[int, str]] = []
    for index, message in enumerate(conversation):
        role = (
            message.role
            if isinstance(message, ConversationMessage)
            else message.get("role")
        )
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
        if isinstance(metadata, Mapping):
            metadata_map = cast(Mapping[str, Any], metadata)
            question_answer = metadata_map.get("question_answer")
            if isinstance(
                question_answer, Mapping
            ) and _looks_like_structured_answer_echo(
                content,
                cast(Mapping[str, Any], question_answer),
            ):
                continue
        messages.append((index, content.casefold()))
    return messages


def _aggregate_user_text(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    *,
    include_structured_answers: bool,
) -> str:
    parts: list[str] = []
    for message in conversation:
        role = (
            message.role
            if isinstance(message, ConversationMessage)
            else message.get("role")
        )
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
            metadata_map = cast(Mapping[str, Any], metadata)
            question_answer = metadata_map.get("question_answer")
            if isinstance(
                question_answer, Mapping
            ) and _looks_like_structured_answer_echo(
                content,
                cast(Mapping[str, Any], question_answer),
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

    if not _has_real_structured_answer_payload(question_answer):
        return False

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
        for raw_value in cast(Sequence[object], raw_values):
            if isinstance(raw_value, str) and raw_value:
                candidates.add(raw_value.casefold())

    if normalized_content in candidates:
        return True
    normalized_without_terminal_punctuation = normalized_content.rstrip(" .?!")
    if (
        normalized_without_terminal_punctuation
        and normalized_without_terminal_punctuation in candidates
    ):
        return True

    return (
        len(normalized_without_terminal_punctuation) <= 80
        and len(normalized_without_terminal_punctuation.split()) <= 4
        and not any(marker in normalized_content for marker in ("\n",))
        and normalized_content == normalized_without_terminal_punctuation
    )


def _has_real_structured_answer_payload(question_answer: Mapping[str, Any]) -> bool:
    question_id = question_answer.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return False

    for key in (
        "selected_option_id",
        "selected_value",
        "answer",
        "custom_value",
    ):
        raw_value = question_answer.get(key)
        if isinstance(raw_value, str) and raw_value:
            return True

    for key in ("selected_option_ids", "selected_values"):
        raw_values = question_answer.get(key)
        if not isinstance(raw_values, Sequence):
            continue
        if any(
            isinstance(raw_value, str) and raw_value
            for raw_value in cast(Sequence[object], raw_values)
        ):
            return True

    return False


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
    if any(
        candidate in message or message in candidate
        for candidate in normalized_candidates
    ):
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
        role = (
            message.role
            if isinstance(message, ConversationMessage)
            else message.get("role")
        )
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
            if role == "tool" and isinstance(metadata, dict):
                requirements_summary = cast(JsonObject, metadata).get(
                    "requirements_summary"
                )
                if isinstance(requirements_summary, Mapping):
                    signals.update(
                        _extract_requirements_summary_signals(
                            cast(Mapping[str, Any], requirements_summary)
                        )
                    )
            continue

        answer = (
            cast(JsonObject, metadata).get("question_answer")
            if isinstance(metadata, dict)
            else None
        )

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
        answer = normalize_question_answer(cast(Mapping[str, Any], answer))
        question_id = answer.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            continue

        values: set[str] = set()
        for raw_values in (
            answer.get("selected_option_ids"),
            answer.get("selected_values"),
        ):
            if not isinstance(raw_values, list):
                continue
            for value in cast(list[object], raw_values):
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


def _extract_requirements_summary_signals(
    requirements_summary: Mapping[str, Any],
) -> dict[str, set[str]]:
    signals: dict[str, set[str]] = {}
    input_description = normalize_signal_text(
        str(requirements_summary.get("input_description") or "")
    )
    input_intent = resolve_input_intent(input_description, {})
    if input_intent.primary_runtime_input != "unknown":
        signals["input_material_mode"] = {input_intent.primary_runtime_input}

    output_description = normalize_signal_text(
        str(requirements_summary.get("output_description") or "")
    )
    output_intent = resolve_output_intent(output_description, {})
    if output_intent.terminal_output is not None:
        signals["final_output_mode"] = {output_intent.terminal_output}
    return signals


def question_is_already_resolved(
    question_id: str,
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    *,
    flow: Flow | None = None,
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
        return bool(
            flow_defaults.get("docx_output_mode")
        ) and not mentions_output_change(freeform_text)

    values = answer_signals.get(canonical_id, set())
    if values:
        return True

    return bool(flow_defaults.get(canonical_id)) and not mentions_output_change(
        freeform_text
    )


def resolve_explicit_output_choice(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    flow_defaults: dict[str, set[str]] | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    scoped_text = build_role_scoped_text(normalized_text)
    replacement_target = _resolve_replacement_output_choice(
        scoped_text,
        answer_signals,
    )
    if replacement_target is not None:
        return replacement_target

    direct_output = _resolve_direct_output_choice(
        scoped_text,
        answer_signals,
    )
    if direct_output is not None:
        return direct_output

    if (
        flow_defaults
        and "final_output_mode" in flow_defaults
        and not mentions_output_change(normalized_text)
    ):
        defaults = flow_defaults["final_output_mode"]
        return next(iter(defaults)) if defaults else None

    if _looks_like_text_analysis_output(normalized_text):
        return "structured_text"
    if _infer_output_content_shape(normalized_text) == "structured_report":
        return "structured_text"

    return None


def _resolve_replacement_output_choice(
    scoped_text: RoleScopedText,
    answer_signals: dict[str, set[str]],
) -> str | None:
    target_text = scoped_text.replacement_target_text
    source_text = scoped_text.replacement_source_text
    if target_text and source_text:
        target_output = _resolve_direct_output_choice(
            build_role_scoped_text(target_text),
            answer_signals,
        )
        replaced_output = _resolve_direct_output_choice(
            build_role_scoped_text(source_text),
            {},
        )
        if target_output is not None and target_output != replaced_output:
            return target_output
    return None


def _resolve_direct_output_choice(
    scoped_text: RoleScopedText,
    answer_signals: dict[str, set[str]],
) -> str | None:
    output_values = answer_signals.get("final_output_mode", set())
    pdf_generation_values = answer_signals.get("pdf_generation_mode", set())
    role_scoped_text = scoped_text.preferred_output_text()
    fallback_text = scoped_text.full_text
    if "docx_document" in output_values:
        return "docx_document"
    if "pdf_document" in output_values:
        return "pdf_document"
    if "structured_json" in output_values:
        return "structured_json"
    if "structured_text" in output_values:
        return "structured_text"
    docx_index = _first_phrase_index(role_scoped_text, DOCX_CONTEXT_MARKERS)
    pdf_index = _first_phrase_index(role_scoped_text, PDF_OUTPUT_CONTEXT_MARKERS)
    if docx_index is not None and (pdf_index is None or docx_index <= pdf_index):
        return "docx_document"
    if role_scoped_text and (
        pdf_generation_values.intersection({"generated_pdf", "pdf_template_requested"})
        or pdf_index is not None
    ):
        return "pdf_document"
    explicit_output_role_text = (
        scoped_text.replacement_target_text or scoped_text.output_text
    )
    if contains_phrase(explicit_output_role_text, "docx") or contains_phrase(
        explicit_output_role_text,
        "word",
    ):
        return "docx_document"
    if contains_phrase(explicit_output_role_text, "pdf"):
        return "pdf_document"
    if contains_any_phrase(
        fallback_text,
        (
            "text summary",
            "textsammanfattning",
            "kort textsammanfattning",
            "sammanfattning som text",
        ),
    ):
        return "structured_text"
    if _looks_like_text_terminal_output(role_scoped_text or fallback_text):
        return "structured_text"
    if _looks_like_final_json_output(role_scoped_text or fallback_text):
        return "structured_json"
    if _looks_like_pdf_template_expectation(role_scoped_text or fallback_text):
        return "pdf_document"
    return None


def _looks_like_text_terminal_output(text: str) -> bool:
    if not text:
        return False
    if contains_any_phrase(
        text,
        (
            "docx",
            "word",
            "pdf",
            "json",
            "spreadsheet",
            "kalkylblad",
            "excel",
        ),
    ):
        return False
    return contains_any_phrase(
        text,
        (
            "kort svar",
            "short answer",
            "brief answer",
            "slutversion",
            "final version",
            "textresultat",
            "text output",
            "text response",
        ),
    )


def _looks_like_final_json_output(text: str) -> bool:
    """Return true only when JSON is requested as the terminal artifact.

    Bare mentions of JSON are common in prompts that ask for examples of
    payloads, schemas, or data between nodes. Treating those as final-output
    intent makes the builder skip the output-format question and silently
    choose structured JSON. The intent must therefore be scoped to final
    output/response wording, or come from the explicit structured answer path.
    """

    normalized = normalize_signal_text(text)
    if not normalized or "json" not in normalized:
        return False
    if contains_any_phrase(
        normalized,
        (
            "example json",
            "json example",
            "exempel json",
            "json exempel",
            "json struktur",
            "json structure",
            "json schema",
            "payload json",
            "json payload",
            "between nodes",
            "mellan noder",
            "per steg",
            "per step",
        ),
    ):
        return False
    return contains_any_phrase(
        normalized,
        (
            "structured json",
            "strukturerad json",
            "json output",
            "output json",
            "output as json",
            "output ska vara json",
            "utdata ska vara json",
            "slutresultat json",
            "slutresultatet ska vara json",
            "final output json",
            "final output should be json",
            "return json",
            "returnera json",
            "respond with json",
            "svara med json",
            "only json",
            "enbart json",
            "bara json",
            "valid json",
            "giltig json",
            "machine readable json",
            "maskinlasbar json",
        ),
    )


def resolve_docx_output_mode(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    explicit_output: str | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    scoped_text = build_role_scoped_text(normalized_text)
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

    output_text = scoped_text.preferred_output_text()
    has_docx_context = contains_any_phrase(output_text, DOCX_CONTEXT_MARKERS)
    if not has_docx_context:
        return (
            "generated_docx"
            if "docx_document" in answer_signals.get("final_output_mode", set())
            else None
        )

    if contains_any_phrase(output_text, DOCX_GENERATED_MODE_MARKERS):
        return "generated_docx"
    if contains_any_phrase(output_text, DOCX_TEMPLATE_MODE_MARKERS):
        return "template_fill_docx"
    return "generated_docx"


def has_explicit_docx_mode_text(text: str) -> bool:
    return _has_explicit_output_mode_text(
        text,
        context_markers=DOCX_CONTEXT_MARKERS,
        generated_markers=DOCX_GENERATED_MODE_MARKERS,
        template_matcher=lambda output_text: contains_any_phrase(
            output_text,
            DOCX_TEMPLATE_MODE_MARKERS,
        ),
    )


def has_explicit_pdf_mode_text(text: str) -> bool:
    return _has_explicit_output_mode_text(
        text,
        context_markers=PDF_OUTPUT_CONTEXT_MARKERS,
        generated_markers=PDF_GENERATED_MODE_MARKERS,
        template_matcher=_looks_like_pdf_template_expectation,
    )


def resolve_pdf_generation_mode(
    text: str,
    answer_signals: dict[str, set[str]],
    *,
    explicit_output: str | None = None,
) -> str | None:
    normalized_text = normalize_signal_text(text)
    scoped_text = build_role_scoped_text(normalized_text)
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

    output_text = scoped_text.preferred_output_text()
    if contains_any_phrase(output_text, PDF_GENERATED_MODE_MARKERS):
        return "generated_pdf"
    if _looks_like_pdf_template_expectation(output_text):
        return "pdf_template_requested"
    return "generated_pdf"


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


def _has_explicit_output_mode_text(
    text: str,
    *,
    context_markers: Sequence[str],
    generated_markers: Sequence[str],
    template_matcher: Callable[[str], bool],
) -> bool:
    normalized_text = normalize_signal_text(text)
    if not normalized_text:
        return False

    output_text = build_role_scoped_text(normalized_text).preferred_output_text()
    if not output_text or not contains_any_phrase(output_text, context_markers):
        return False

    return contains_any_phrase(output_text, generated_markers) or template_matcher(
        output_text
    )


def _first_phrase_index(text: str, phrases: Sequence[str]) -> int | None:
    if not text:
        return None

    indexes: list[int] = []
    for phrase in phrases:
        normalized_phrase = normalize_signal_text(phrase)
        if not normalized_phrase or normalized_phrase not in text:
            continue
        indexes.append(text.find(normalized_phrase))
    if not indexes:
        return None
    return min(indexes)


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
        "memo",
        "punkter",
        "bullet points",
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
    return infer_runtime_metadata_slot(text) is not None


def runtime_metadata_requested(answer_signals: dict[str, set[str]]) -> bool:
    values = answer_signals.get("runtime_metadata_fields", set())
    return any(
        value in {"basic_case_metadata", "detailed_case_metadata"} for value in values
    )


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
