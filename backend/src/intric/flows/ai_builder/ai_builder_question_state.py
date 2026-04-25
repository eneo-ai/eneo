"""Server-owned conversation state for planner questions.

The planner may author a question prompt, but the backend owns the
mechanics of whether that question has already been asked and whether a
user turn has arrived after it. Keeping that logic deterministic avoids
coupling guardrails to legacy tool-call metadata or to the LLM's ability
to classify free-form answers perfectly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_models import ConversationMessage


@dataclass(frozen=True, slots=True)
class AskedQuestionState:
    asked_question_ids: frozenset[str]
    question_ids_with_new_evidence: frozenset[str]
    has_new_evidence: bool


def derive_asked_question_state(
    conversation: Sequence[ConversationMessage | Mapping[str, Any]],
) -> AskedQuestionState:
    """Derive duplicate-question guard inputs from conversation order.

    `question_ids_with_new_evidence` is question-specific: a question ID
    is included only when a user evidence turn appears after the latest
    assistant ask for that same ID. If the same question is asked again,
    it must receive another user turn before a further repeat is allowed.
    """
    asked: set[str] = set()
    awaiting_evidence: set[str] = set()
    with_new_evidence: set[str] = set()

    for message in conversation:
        question_id = assistant_question_id(message)
        if question_id is not None:
            asked.add(question_id)
            awaiting_evidence.add(question_id)
            with_new_evidence.discard(question_id)
            continue

        if not _is_user_evidence(message):
            continue
        if awaiting_evidence:
            with_new_evidence.update(awaiting_evidence)
            awaiting_evidence.clear()

    return AskedQuestionState(
        asked_question_ids=frozenset(asked),
        question_ids_with_new_evidence=frozenset(with_new_evidence),
        has_new_evidence=bool(with_new_evidence),
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
    if isinstance(metadata, Mapping):
        metadata_map = cast(Mapping[str, Any], metadata)
        question_id = metadata_map.get("question_id")
        if isinstance(question_id, str) and question_id:
            return question_id

    return _question_id_from_legacy_tool_calls(_message_tool_calls(message))


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
    if isinstance(metadata, Mapping):
        metadata_map = cast(Mapping[str, Any], metadata)
        if metadata_map.get("question_answer") or metadata_map.get(
            "requirements_confirmed"
        ):
            return True
        file_ids = metadata_map.get("file_ids")
        if (
            isinstance(file_ids, Sequence)
            and not isinstance(file_ids, str)
            and file_ids
        ):
            return True

    content = (
        message.content
        if isinstance(message, ConversationMessage)
        else message.get("content")
    )
    return isinstance(content, str) and bool(content.strip())


def _message_tool_calls(
    message: ConversationMessage | Mapping[str, Any],
) -> Sequence[object] | None:
    if isinstance(message, ConversationMessage):
        return message.tool_calls
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, Sequence) or isinstance(tool_calls, str):
        return None
    return cast(Sequence[object], tool_calls)


def _question_id_from_legacy_tool_calls(
    tool_calls: Sequence[object] | None,
) -> str | None:
    if tool_calls is None:
        return None
    for tool_call in reversed(tool_calls):
        if not isinstance(tool_call, Mapping):
            continue
        tool_call_map = cast(Mapping[str, Any], tool_call)
        if tool_call_map.get("name") != "ask_structured_question":
            continue
        arguments = tool_call_map.get("arguments")
        payload: object = arguments
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, Mapping):
            continue
        payload_map = cast(Mapping[str, Any], payload)
        question_id = payload_map.get("question_id")
        if isinstance(question_id, str) and question_id:
            return question_id
    return None


__all__ = [
    "AskedQuestionState",
    "assistant_question_id",
    "derive_asked_question_state",
]
