from __future__ import annotations

from typing import Iterable

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_has_requirements_summary,
    question_answer_from_metadata,
    question_answer_question_id,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_version_from_metadata,
    tool_call_ids,
    tool_calls_from_message,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    extract_freeform_user_messages,
)

MAX_SESSION_MESSAGES = 60
TAIL_SESSION_MESSAGES = 40


def compact_ai_builder_conversation(
    conversation: list[ConversationMessage],
    *,
    max_messages: int = MAX_SESSION_MESSAGES,
    tail_messages: int = TAIL_SESSION_MESSAGES,
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
