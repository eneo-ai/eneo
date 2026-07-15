from __future__ import annotations

import json
from typing import Iterable

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_has_requirements_summary,
    question_answer_from_metadata,
    question_answer_question_id,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_version_from_metadata,
    tool_call_ids,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    extract_freeform_user_messages,
)

# Versioned persistence limits for the BuilderSessions JSON aggregate. These are
# deliberately independent of model context windows: provider request assembly
# derives its token budget from the selected model in
# ai_builder_planner_request_preparation. Changing these limits requires the same
# review and PostgreSQL measurement as changing the aggregate itself; they are not
# tenant/admin settings.
MAX_SESSION_MESSAGES = 60
TAIL_SESSION_MESSAGES = 40
MAX_SESSION_MESSAGE_BYTES = 256 * 1024
MAX_SESSION_CONVERSATION_BYTES = 1024 * 1024


def compact_ai_builder_conversation(
    conversation: list[ConversationMessage],
    *,
    max_messages: int = MAX_SESSION_MESSAGES,
    tail_messages: int = TAIL_SESSION_MESSAGES,
    max_message_bytes: int = MAX_SESSION_MESSAGE_BYTES,
    max_conversation_bytes: int = MAX_SESSION_CONVERSATION_BYTES,
) -> list[ConversationMessage]:
    message_sizes = [
        _message_serialized_size_bytes(message) for message in conversation
    ]
    for message_size in message_sizes:
        if message_size > max_message_bytes:
            raise ValueError(
                "AI Builder conversation message exceeds the serialized byte limit."
            )

    compacted = _compact_by_message_count(
        conversation,
        max_messages=max_messages,
        tail_messages=tail_messages,
    )
    compacted_sizes = [_message_serialized_size_bytes(message) for message in compacted]
    serialized_size = _conversation_size_from_message_sizes(compacted_sizes)
    if serialized_size <= max_conversation_bytes:
        return compacted

    protected_indices = _required_message_indices(compacted)
    if compacted:
        protected_indices.add(len(compacted) - 1)
    selected_indices = list(range(len(compacted)))
    selected_count = len(selected_indices)
    for index in selected_indices.copy():
        if index in protected_indices:
            continue
        selected_indices.remove(index)
        serialized_size -= compacted_sizes[index]
        if selected_count > 1:
            serialized_size -= 1
        selected_count -= 1
        if serialized_size <= max_conversation_bytes:
            return [compacted[selected_index] for selected_index in selected_indices]

    raise ValueError(
        "Required AI Builder conversation context exceeds the serialized byte limit."
    )


def conversation_serialized_size_bytes(
    conversation: list[ConversationMessage],
) -> int:
    return _conversation_size_from_message_sizes(
        [_message_serialized_size_bytes(message) for message in conversation]
    )


def _message_serialized_size_bytes(message: ConversationMessage) -> int:
    return len(_compact_json_bytes(message.model_dump(mode="json")))


def _conversation_size_from_message_sizes(message_sizes: list[int]) -> int:
    comma_bytes = max(0, len(message_sizes) - 1)
    return 2 + sum(message_sizes) + comma_bytes


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _compact_by_message_count(
    conversation: list[ConversationMessage],
    *,
    max_messages: int,
    tail_messages: int,
) -> list[ConversationMessage]:
    if len(conversation) <= max_messages:
        return list(conversation)

    preserved_indices = set(
        range(max(0, len(conversation) - tail_messages), len(conversation))
    )
    required_groups: list[list[int]] = []

    requirements_index = _latest_requirements_summary_index(conversation)
    if requirements_index is not None:
        group = [requirements_index]
        previous_request_index = _latest_user_request_before_index(
            conversation,
            requirements_index,
        )
        if previous_request_index is not None:
            group.insert(0, previous_request_index)
        confirmation_index = _matching_requirements_confirmation_index(
            conversation, requirements_index
        )
        if confirmation_index is not None:
            group.append(confirmation_index)
        preserved_indices.update(group)
        required_groups.append(group)

    structured_answer_indices = list(_latest_structured_answer_indices(conversation))
    if structured_answer_indices:
        preserved_indices.update(structured_answer_indices)
        required_groups.extend([[index] for index in structured_answer_indices])

    tool_trace_group = list(_latest_tool_trace_indices(conversation))
    if tool_trace_group:
        preserved_indices.update(tool_trace_group)
        required_groups.append(tool_trace_group)

    compacted = [conversation[index] for index in sorted(preserved_indices)]
    if len(compacted) <= max_messages:
        return compacted

    selected_indices = sorted(preserved_indices)[-max_messages:]
    selected_indices = _preserve_required_groups(
        selected_indices=selected_indices,
        required_groups=required_groups,
        max_messages=max_messages,
    )
    return [conversation[index] for index in selected_indices]


def _required_message_indices(
    conversation: list[ConversationMessage],
) -> set[int]:
    required_indices: set[int] = set()
    requirements_index = _latest_requirements_summary_index(conversation)
    if requirements_index is not None:
        required_indices.add(requirements_index)
        previous_request_index = _latest_user_request_before_index(
            conversation,
            requirements_index,
        )
        if previous_request_index is not None:
            required_indices.add(previous_request_index)
        confirmation_index = _matching_requirements_confirmation_index(
            conversation,
            requirements_index,
        )
        if confirmation_index is not None:
            required_indices.add(confirmation_index)
    required_indices.update(_latest_structured_answer_indices(conversation))
    required_indices.update(_latest_tool_trace_indices(conversation))
    return required_indices


def _latest_requirements_summary_index(
    conversation: list[ConversationMessage],
) -> int | None:
    for index in range(len(conversation) - 1, -1, -1):
        if metadata_has_requirements_summary(conversation[index].metadata):
            return index
    return None


def _matching_requirements_confirmation_index(
    conversation: list[ConversationMessage],
    summary_index: int,
) -> int | None:
    summary = requirements_summary_from_metadata(conversation[summary_index].metadata)
    version = (
        summary.requirements_version
        if summary is not None
        else requirements_version_from_metadata(conversation[summary_index].metadata)
    )
    for index in range(summary_index + 1, len(conversation)):
        if conversation[index].role != "user":
            continue
        confirmation = requirements_confirmation_from_metadata(
            conversation[index].metadata
        )
        if confirmation is None:
            continue
        if version is None or confirmation.requirements_version == version:
            return index
    return None


def _latest_user_request_before_index(
    conversation: list[ConversationMessage],
    before_index: int,
) -> int | None:
    freeform_messages = extract_freeform_user_messages(conversation[:before_index])
    for index, _text in reversed(freeform_messages):
        if requirements_confirmation_from_metadata(conversation[index].metadata):
            continue
        return index
    return None


def _latest_structured_answer_indices(
    conversation: list[ConversationMessage],
) -> Iterable[int]:
    latest_by_question: dict[str, int] = {}
    for index, message in enumerate(conversation):
        if message.role != "user":
            continue
        question_answer = question_answer_from_metadata(message.metadata)
        if question_answer is None:
            continue
        question_id = question_answer_question_id(question_answer)
        if question_id is not None:
            latest_by_question[canonical_question_id(question_id)] = index
    return sorted(latest_by_question.values())


def _latest_tool_trace_indices(
    conversation: list[ConversationMessage],
) -> Iterable[int]:
    for index in range(len(conversation) - 1, -1, -1):
        tool_calls = tool_calls_from_message(conversation[index])
        if conversation[index].role == "assistant" and tool_calls:
            indices = [index]
            ids = tool_call_ids(tool_calls)
            cursor = index + 1
            while cursor < len(conversation):
                candidate = conversation[cursor]
                if candidate.role != "tool" or candidate.tool_call_id not in ids:
                    break
                indices.append(cursor)
                cursor += 1
            return indices
    return []


def _preserve_required_groups(
    *,
    selected_indices: list[int],
    required_groups: list[list[int]],
    max_messages: int,
) -> list[int]:
    selected = list(selected_indices)
    protected = {index for group in required_groups for index in group}

    for group in required_groups:
        in_selected = [index for index in group if index in selected]
        if len(in_selected) == len(group):
            continue

        selected = [index for index in selected if index not in group]
        while len(selected) + len(group) > max_messages:
            drop_index = next(
                (index for index in selected if index not in protected),
                selected[0],
            )
            selected.remove(drop_index)
        selected.extend(group)
        selected.sort()

    return selected[-max_messages:]
