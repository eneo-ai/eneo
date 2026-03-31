from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_discovery import build_discovery_block_message

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.flows.ai_builder.ai_builder_models import ConversationMessage


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
        metadata = msg.metadata if isinstance(msg.metadata, dict) else None
        if metadata is None:
            continue
        qa = metadata.get("question_answer")
        if not isinstance(qa, dict):
            continue
        qid = qa.get("question_id")
        if isinstance(qid, str):
            answered_ids.add(qid)
    return len(answered_ids)


def build_question_fallback_text(arguments: dict[str, Any]) -> str | None:
    question = arguments.get("question")
    question_id = arguments.get("question_id")
    if not isinstance(question, str) or not question.strip():
        if isinstance(question_id, str) and question_id:
            question = "Jag behöver förtydliga nästa designval innan jag bygger vidare."
        else:
            return None

    lines = [question.strip()]
    options = arguments.get("options")
    if isinstance(options, list):
        labels = [
            str(option.get("label")).strip()
            for option in options
            if isinstance(option, dict) and isinstance(option.get("label"), str)
        ]
        if labels:
            if len(labels) == 1:
                lines.append(f"Föreslaget alternativ: {labels[0]}")
            else:
                lines.append("Alternativ:")
                lines.extend(f"- {label}" for label in labels)

    lines.append("Svara gärna i fri text så bygger jag vidare.")
    return "\n".join(lines)


def looks_like_information_request(text: str) -> bool:
    lowered = text.casefold()
    if "?" not in text or len(text.strip()) >= 240:
        return False
    # Action-intent keywords -> user wants to build/change, not ask.
    action_keywords = (
        "proposal", "förslag", "plan", "steg", "steps", "flow",
        "bygg", "skapa", "lägg till", "ändra", "ta bort",
        "build", "create", "add", "remove", "modify", "make",
    )
    return not any(keyword in lowered for keyword in action_keywords)
