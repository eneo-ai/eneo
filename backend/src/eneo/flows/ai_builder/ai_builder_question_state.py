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

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_canonicalization import (
    canonical_question_id,
    is_supported_structured_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    assistant_question_id_from_metadata,
    assistant_question_index_from_metadata,
    file_ids_from_metadata,
    metadata_has_question_answer,
    question_response_from_metadata,
    requirements_confirmation_from_metadata,
    structured_question_payload_from_tool_arguments,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    question_exposure_for_id,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)


def _message_metadata(message: ConversationMessage | Mapping[str, Any]) -> object:
    if isinstance(message, ConversationMessage):
        return message.metadata
    return message.get("metadata")


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

    question_id = assistant_question_id_from_metadata(_message_metadata(message))
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

    metadata = _message_metadata(message)
    if metadata_has_question_answer(metadata):
        return True
    if question_response_from_metadata(metadata) is not None:
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
        response = question_response_from_metadata(_message_metadata(message))
        if response is not None:
            last_question_id = response.question_id
            content = (
                message.content
                if isinstance(message, ConversationMessage)
                else message.get("content")
            )
            latest_answer = (
                content.strip()
                if isinstance(content, str) and content.strip()
                else None
            )
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


def question_ordinal_in_session(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
    *,
    question_id: str,
) -> int:
    """Where this question sits in the sequence the user has been walked through.

    Counted over the questions actually put to the user, not the ones they
    answered, because the number they read has to match what they have seen. A
    question asked again keeps the place it already had, so re-asking a
    question never makes the sequence appear to grow.

    A number the user has already seen is read back off the message it was
    stamped on rather than recounted, because message order is not stable:
    compaction keeps the latest interaction of a re-asked question, which moves
    that question behind ones it was asked before. Counting positions is the
    fallback for questions persisted before the number travelled with them.
    """

    numbered: dict[str, int] = {}
    for message in conversation:
        asked_id = assistant_question_id(message)
        if asked_id is None or asked_id in numbered:
            continue
        persisted = assistant_question_index_from_metadata(_message_metadata(message))
        numbered[asked_id] = (
            persisted if persisted is not None else _next_question_ordinal(numbered)
        )
    already_seen = numbered.get(canonical_question_id(question_id))
    if already_seen is not None:
        return already_seen
    return _next_question_ordinal(numbered)


def _next_question_ordinal(numbered: Mapping[str, int]) -> int:
    return max(numbered.values(), default=0) + 1


def pending_user_requirement_question_id(
    conversation: Sequence[ConversationMessage],
) -> str | None:
    pending = _pending_user_requirement_question(conversation)
    return pending[0] if pending is not None else None


def pending_user_requirement_question(
    conversation: Sequence[ConversationMessage],
) -> StructuredQuestionPayload | None:
    """The question the user is answering right now, exactly as they saw it.

    Only a still-open question can be settled, and a payload the server can no
    longer validate — or that names a different question than the one this
    owner says is open — is not evidence of what was offered.
    """
    pending = _pending_user_requirement_question(conversation)
    if pending is None or pending[1] is None:
        return None
    try:
        payload = StructuredQuestionPayload.model_validate(pending[1])
    except ValidationError:
        return None
    if canonical_question_id(payload.question_id) != pending[0]:
        return None
    return payload


def _pending_user_requirement_question(
    conversation: Sequence[ConversationMessage],
) -> tuple[str, Mapping[str, Any] | None] | None:
    pending: tuple[str, Mapping[str, Any] | None] | None = None
    for message in conversation:
        question_id = assistant_question_id(message)
        if question_id is not None:
            pending = (
                (question_id, _structured_question_arguments(message))
                if is_supported_structured_question_id(question_id)
                and question_exposure_for_id(question_id) == "user_requirement"
                else None
            )
            continue
        if pending is not None and _is_user_evidence(message):
            pending = None
    return pending


def _structured_question_arguments(
    message: ConversationMessage | Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for tool_call in reversed(tool_calls_from_message(message)):
        if tool_call.name != ASK_STRUCTURED_QUESTION_TOOL_NAME:
            continue
        payload = structured_question_payload_from_tool_arguments(tool_call.arguments)
        if payload is not None:
            return payload
    return None


__all__ = [
    "assistant_question_id",
    "last_answered_question",
    "pending_user_requirement_question",
    "pending_user_requirement_question_id",
    "question_ordinal_in_session",
]
