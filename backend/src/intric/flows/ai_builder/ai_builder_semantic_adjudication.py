from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
    DiscoveryLanguage,
    SemanticAdjudicationResult,
    SemanticAdjudicationSignal,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import (
    question_suggestion_for_id,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    latest_pending_structured_question,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.main.logging import get_logger

logger = get_logger(__name__)

_SEMANTIC_CACHE: dict[str, SemanticAdjudicationResult] = {}
_MAX_CACHE_ENTRIES = 128
_NON_ADJUDICABLE_QUESTION_IDS = frozenset(
    {
        # DOCX generation strategy changes downstream implementation and manual setup.
        # Keep it as an explicit user choice instead of letting semantic adjudication guess.
        "docx_output_mode",
    }
)


def should_run_semantic_adjudication(analysis: DiscoveryAnalysis) -> bool:
    if not analysis.mvs_met:
        return False
    if analysis.next_issue is not None:
        return False

    for candidate in analysis.candidates:
        if candidate.impact == "polish":
            continue
        if candidate.confidence != "low":
            continue
        if candidate.question_id is None:
            continue
        if candidate.question_id in _NON_ADJUDICABLE_QUESTION_IDS:
            continue
        return True
    return False


async def adjudicate_discovery_semantics(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    conversation: list[ConversationMessage],
    analysis: DiscoveryAnalysis,
    ui_language: str | None = None,
) -> SemanticAdjudicationResult | None:
    candidate_ids = [
        candidate.question_id
        for candidate in analysis.candidates
        if candidate.question_id is not None
        and candidate.question_id not in _NON_ADJUDICABLE_QUESTION_IDS
        and candidate.impact in {"architecture", "quality"}
        and candidate.confidence == "low"
    ]
    if not candidate_ids:
        return None

    text = aggregate_freeform_user_text(conversation)
    if not text.strip():
        return None

    cache_key = _semantic_cache_key(
        text=text,
        ui_language=ui_language,
        question_ids=candidate_ids,
    )
    cached = _SEMANTIC_CACHE.get(cache_key)
    if cached is not None:
        return SemanticAdjudicationResult(
            signals=cached.signals,
            assumptions=cached.assumptions,
            contradictions=cached.contradictions,
            cached=True,
        )

    prompt = _build_semantic_prompt(
        text=text,
        question_ids=candidate_ids,
        ui_language=ui_language,
    )
    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=prompt,
            stream=False,
            drop_params=True,
            max_tokens=500,
            temperature=0.0,
            **litellm_kwargs,
        )
    except Exception as error:
        logger.warning("Semantic adjudication failed", exc_info=error)
        return None

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        return None

    result = _parse_semantic_response(content, allowed_question_ids=candidate_ids)
    if result is None:
        return None

    _remember_cache(cache_key, result)
    return result


async def adjudicate_pending_question_answer(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    conversation: list[ConversationMessage],
    user_message: str,
) -> dict[str, Any] | None:
    pending = latest_pending_structured_question(conversation)
    if not isinstance(pending, dict):
        return None

    question_id = pending.get("question_id")
    question = pending.get("question")
    options = pending.get("options")
    if (
        not isinstance(question_id, str)
        or not isinstance(question, str)
        or not isinstance(options, list)
    ):
        return None

    valid_option_ids: dict[str, str] = {}
    for option in cast(list[object], options):
        if not isinstance(option, dict):
            continue
        option_dict = cast(dict[str, Any], option)
        option_id = option_dict.get("id")
        if not isinstance(option_id, str):
            continue
        option_value = option_dict.get("value", option_id)
        valid_option_ids[option_id] = (
            option_value if isinstance(option_value, str) else option_id
        )
    if not valid_option_ids:
        return None

    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify a user's freeform answer to a structured question. "
                        "Return JSON only in the format "
                        '{"selected_option_id": string|null, "reason": string}.'
                    ),
                },
                {
                    "role": "user",
                    "content": _build_answer_prompt(
                        question=question,
                        options=cast(list[dict[str, Any]], options),
                        user_message=user_message,
                    ),
                },
            ],
            stream=False,
            drop_params=True,
            max_tokens=120,
            temperature=0.0,
            **litellm_kwargs,
        )
    except Exception as error:
        logger.warning("Pending-question adjudication failed", exc_info=error)
        return None

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None
    option_id = (
        cast(dict[str, Any], raw).get("selected_option_id")
        if isinstance(raw, dict)
        else None
    )
    if not isinstance(option_id, str) or option_id not in valid_option_ids:
        return None

    selected_value = valid_option_ids[option_id]
    return {
        "question_id": question_id,
        "selected_option_ids": [option_id],
        "selected_values": [selected_value],
    }


def _build_semantic_prompt(
    *,
    text: str,
    question_ids: Iterable[str],
    ui_language: str | None,
) -> list[dict[str, str]]:
    dimension_lines: list[str] = []
    language: DiscoveryLanguage = "en" if ui_language == "en" else "sv"
    for question_id in question_ids:
        suggestion = question_suggestion_for_id(question_id, language=language)
        if suggestion is None:
            continue
        options = ", ".join(
            f"{option.value or option.id} ({option.label})"
            for option in suggestion.options
        )
        dimension_lines.append(f"- {question_id}: {options}")

    system = (
        "You classify unresolved flow-builder intent into constrained enum values. "
        "Return JSON only. Never explain outside the schema. "
        "Use a signal only when the conversation provides real evidence. "
        "If still ambiguous, omit the signal instead of guessing."
    )
    user = (
        "Conversation summary:\n"
        f"{text}\n\n"
        "Unresolved dimensions and allowed values:\n"
        f"{chr(10).join(dimension_lines)}\n\n"
        "Return JSON with this shape:\n"
        "{"
        '"signals": [{"question_id": str, "value": str, "confidence": "high"|"medium"|"low", "reason": str}], '
        '"assumptions": [str], '
        '"contradictions": [str]'
        "}\n"
        "Use only the listed question_id values and option values."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_answer_prompt(
    *,
    question: str,
    options: list[dict[str, Any]],
    user_message: str,
) -> str:
    option_lines: list[str] = []
    for option in options:
        option_id = option.get("id")
        label = option.get("label")
        description = option.get("description")
        if not isinstance(option_id, str) or not isinstance(label, str):
            continue
        suffix = (
            f" — {description}" if isinstance(description, str) and description else ""
        )
        option_lines.append(f"- {option_id}: {label}{suffix}")
    return (
        f"Question:\n{question}\n\n"
        f"Options:\n{chr(10).join(option_lines)}\n\n"
        f"User answer:\n{user_message}\n\n"
        "Return the best matching option id or null if the answer is too ambiguous."
    )


def _parse_semantic_response(
    content: str,
    *,
    allowed_question_ids: list[str],
) -> SemanticAdjudicationResult | None:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, dict):
        return None
    raw_dict = cast(dict[str, Any], raw)

    allowed = set(allowed_question_ids)
    signals: list[SemanticAdjudicationSignal] = []
    for item in cast(list[object], raw_dict.get("signals", [])):
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        question_id = item_dict.get("question_id")
        value = item_dict.get("value")
        confidence = item_dict.get("confidence")
        reason = item_dict.get("reason")
        if question_id not in allowed:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        if confidence not in {"high", "medium", "low"}:
            continue
        signals.append(
            SemanticAdjudicationSignal(
                question_id=question_id,
                value=value.strip(),
                confidence=confidence,
                reason=reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "semantic adjudication",
            )
        )

    assumptions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("assumptions", []))
        if isinstance(item, str) and item.strip()
    )
    contradictions = tuple(
        item.strip()
        for item in cast(list[object], raw_dict.get("contradictions", []))
        if isinstance(item, str) and item.strip()
    )
    return SemanticAdjudicationResult(
        signals=tuple(signals),
        assumptions=assumptions,
        contradictions=contradictions,
    )


def _semantic_cache_key(
    *,
    text: str,
    ui_language: str | None,
    question_ids: list[str],
) -> str:
    payload = json.dumps(
        {
            "text": text,
            "ui_language": ui_language,
            "question_ids": sorted(question_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _remember_cache(key: str, result: SemanticAdjudicationResult) -> None:
    if len(_SEMANTIC_CACHE) >= _MAX_CACHE_ENTRIES:
        oldest_key = next(iter(_SEMANTIC_CACHE))
        _SEMANTIC_CACHE.pop(oldest_key, None)
    _SEMANTIC_CACHE[key] = result
