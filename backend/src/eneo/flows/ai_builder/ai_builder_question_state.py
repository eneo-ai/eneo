"""Server-owned conversation state for planner questions.

The planner may author a question prompt, but the backend owns the
mechanics of whether that question has already been asked and whether a
user turn has arrived after it. Keeping that logic deterministic avoids
coupling guardrails to legacy tool-call metadata or to the LLM's ability
to classify free-form answers perfectly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eneo.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    assistant_question_id_from_metadata,
    file_ids_from_metadata,
    metadata_has_question_answer,
    requirements_confirmation_from_metadata,
    structured_question_payload_from_tool_arguments,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)


def assistant_question_id(
    message: ConversationMessage | Mapping[str, Any],
) -> str | None:
    role = (
        message.role
        if isinstance(message, ConversationMessage)
        else message.get("role")
    )
    if role != "assistant":
        return None

    metadata = (
        message.metadata
        if isinstance(message, ConversationMessage)
        else message.get("metadata")
    )
    question_id = assistant_question_id_from_metadata(metadata)
    if question_id is not None:
        return canonical_question_id(question_id)

    tool_question_id = _question_id_from_legacy_tool_calls(message)
    if tool_question_id is None:
        return None
    return canonical_question_id(tool_question_id)


def _is_user_evidence(message: ConversationMessage | Mapping[str, Any]) -> bool:
    role = (
        message.role
        if isinstance(message, ConversationMessage)
        else message.get("role")
    )
    if role != "user":
        return False

    metadata = (
        message.metadata
        if isinstance(message, ConversationMessage)
        else message.get("metadata")
    )
    if metadata_has_question_answer(metadata):
        return True
    if requirements_confirmation_from_metadata(metadata) is not None:
        return True
    if file_ids_from_metadata(metadata):
        return True

    content = (
        message.content
        if isinstance(message, ConversationMessage)
        else message.get("content")
    )
    return isinstance(content, str) and bool(content.strip())


def _question_id_from_legacy_tool_calls(
    message: ConversationMessage | Mapping[str, Any],
) -> str | None:
    for tool_call in reversed(tool_calls_from_message(message)):
        if tool_call.name != ASK_STRUCTURED_QUESTION_TOOL_NAME:
            continue
        payload = structured_question_payload_from_tool_arguments(tool_call.arguments)
        if payload is None:
            continue
        question_id = payload.get("question_id")
        if isinstance(question_id, str) and question_id:
            return question_id
    return None


def last_answered_question(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> tuple[str, str] | None:
    """The most recently asked question the user has since replied to in text.

    Returns ``(question_id, latest_user_answer)`` when the last assistant
    question is followed by a free-text user reply, so targeted slot
    classification can bias toward that question's slot. Returns ``None`` when no
    question was asked, the latest turn is still the question, or the reply
    carried no free text.
    """
    last_question_id: str | None = None
    latest_answer: str | None = None
    for message in conversation:
        question_id = assistant_question_id(message)
        if question_id is not None:
            last_question_id = question_id
            latest_answer = None
            continue
        if last_question_id is None or not _is_user_evidence(message):
            continue
        content = (
            message.content
            if isinstance(message, ConversationMessage)
            else message.get("content")
        )
        if isinstance(content, str) and content.strip():
            latest_answer = content.strip()
    if last_question_id is None or latest_answer is None:
        return None
    return last_question_id, latest_answer


__all__ = [
    "assistant_question_id",
    "last_answered_question",
]
