from __future__ import annotations

from typing import TYPE_CHECKING

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    question_answer_from_metadata,
    question_answer_question_id,
)
from intric.flows.ai_builder.ai_builder_discovery import build_discovery_block_message

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_domain_models import (
        ConversationMessage,
    )
    from intric.flows.domain.flow import Flow


# Minimum number of structured answers before we allow bypassing soft blockers
_DISCOVERY_SUFFICIENT_ANSWERS = 4


def analyze_discovery_ready(
    conversation: list["ConversationMessage"],
    *,
    flow: "Flow | None" = None,
) -> bool:
    if build_discovery_block_message(conversation, flow=flow) is None:
        return True
    structured_count = _count_structured_answers(conversation)
    return structured_count >= _DISCOVERY_SUFFICIENT_ANSWERS


def _count_structured_answers(conversation: list["ConversationMessage"]) -> int:
    """Count distinct structured question answers in the conversation."""
    answered_ids: set[str] = set()
    for msg in conversation:
        if msg.role != "user":
            continue
        answer = question_answer_from_metadata(msg.metadata)
        if answer is None:
            continue
        question_id = question_answer_question_id(answer)
        if question_id is not None:
            answered_ids.add(question_id)
    return len(answered_ids)


def looks_like_information_request(text: str) -> bool:
    lowered = text.casefold()
    if "?" not in text or len(text.strip()) >= 240:
        return False
    # Action-intent keywords -> user wants to build/change, not ask.
    action_keywords = (
        "proposal",
        "förslag",
        "plan",
        "steg",
        "steps",
        "flow",
        "bygg",
        "skapa",
        "lägg till",
        "ändra",
        "ta bort",
        "build",
        "create",
        "add",
        "remove",
        "modify",
        "make",
    )
    return not any(keyword in lowered for keyword in action_keywords)
