from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from intric.flows.ai_builder.ai_builder_discovery_questions import (
    question_suggestion_for_id,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    latest_pending_structured_question,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    SlotClassificationResult,
    classify_slots,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    NON_LLM_RESOLVABLE_SLOT_NAMES,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)


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
        if candidate.question_id in NON_LLM_RESOLVABLE_SLOT_NAMES:
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
    tenant_id: UUID,
    ui_language: str | None = None,
) -> SlotClassificationResult | None:
    candidate_ids = [
        candidate.question_id
        for candidate in analysis.candidates
        if candidate.question_id is not None
        and candidate.question_id not in NON_LLM_RESOLVABLE_SLOT_NAMES
        and candidate.impact in {"architecture", "quality"}
        and candidate.confidence == "low"
    ]
    if not candidate_ids:
        return None

    text = aggregate_freeform_user_text(conversation)
    if not text.strip():
        return None

    allowed_values = _candidate_allowed_values(
        candidate_ids=candidate_ids,
        ui_language=ui_language,
    )
    if not allowed_values:
        return None

    return await classify_slots(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        text=text,
        allowed_slot_values=allowed_values,
        tenant_id=tenant_id,
        ui_language=ui_language,
    )


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


def _candidate_allowed_values(
    *,
    candidate_ids: list[str],
    ui_language: str | None,
) -> dict[str, frozenset[str]]:
    language = "en" if ui_language == "en" else "sv"
    allowed: dict[str, frozenset[str]] = {}
    for question_id in candidate_ids:
        suggestion = question_suggestion_for_id(question_id, language=language)
        if suggestion is None:
            continue
        allowed[question_id] = frozenset(
            option.value or option.id for option in suggestion.options
        )
    return allowed


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
