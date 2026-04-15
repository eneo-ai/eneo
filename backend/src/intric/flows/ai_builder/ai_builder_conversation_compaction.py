from __future__ import annotations

from typing import Iterable

from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage

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
        confirmation_index = _matching_requirements_confirmation_index(
            conversation, requirements_index
        )
        if confirmation_index is not None:
            group.append(confirmation_index)
        preserved_indices.update(group)
        required_groups.append(group)

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
        metadata = conversation[index].metadata
        if isinstance(metadata, dict) and isinstance(
            metadata.get("requirements_summary"), dict
        ):
            return index
    return None


def _matching_requirements_confirmation_index(
    conversation: list[ConversationMessage],
    summary_index: int,
) -> int | None:
    summary_metadata = conversation[summary_index].metadata or {}
    version = summary_metadata.get("requirements_version")
    for index in range(summary_index + 1, len(conversation)):
        if conversation[index].role != "user":
            continue
        metadata = conversation[index].metadata
        if not isinstance(metadata, dict):
            continue
        if metadata.get("requirements_confirmed") is True and (
            version is None or metadata.get("requirements_version") == version
        ):
            return index
    return None


def _latest_tool_trace_indices(
    conversation: list[ConversationMessage],
) -> Iterable[int]:
    for index in range(len(conversation) - 1, -1, -1):
        tool_calls = conversation[index].tool_calls
        if conversation[index].role == "assistant" and tool_calls:
            indices = [index]
            tool_call_ids = {
                str(tool_call.get("id"))
                for tool_call in tool_calls
                if tool_call.get("id") is not None
            }
            cursor = index + 1
            while cursor < len(conversation):
                candidate = conversation[cursor]
                if (
                    candidate.role != "tool"
                    or candidate.tool_call_id not in tool_call_ids
                ):
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
