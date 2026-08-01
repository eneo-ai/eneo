from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Iterable, Literal, cast

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SLOT_CLASSIFICATION_METADATA_KEY,
    ClassifierRetentionIdentity,
    metadata_has_requirements_summary,
    metadata_with_slot_classification,
    question_interaction_id_from_metadata,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_version_from_metadata,
    slot_classification_from_metadata,
    tool_call_ids,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    extract_freeform_user_messages,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    SchemaLimitExceeded,
    derive_freeform_schema_candidates,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
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

logger = logging.getLogger(__name__)


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

    original_serialized_size = _conversation_size_from_message_sizes(message_sizes)
    compaction_limits: set[Literal["count", "bytes"]] = set()
    if len(conversation) > max_messages:
        compaction_limits.add("count")
    if original_serialized_size > max_conversation_bytes:
        compaction_limits.add("bytes")
    preferred_message_ids: frozenset[str] = frozenset()
    if compaction_limits:
        conversation = _retain_latest_classifier_semantics(
            conversation,
            compaction_limits=frozenset(compaction_limits),
        )
        preferred_message_ids = _freeform_schema_candidate_message_ids(conversation)
        message_sizes = [
            _message_serialized_size_bytes(message) for message in conversation
        ]
        if any(message_size > max_message_bytes for message_size in message_sizes):
            raise ValueError(
                "Required AI Builder conversation context exceeds the serialized byte "
                "limit."
            )

    retention_units = _conversation_retention_units(conversation)

    compacted = _compact_by_message_count(
        conversation,
        retention_units=retention_units,
        max_messages=max_messages,
        tail_messages=tail_messages,
        preferred_message_ids=preferred_message_ids,
    )
    compacted_sizes = [_message_serialized_size_bytes(message) for message in compacted]
    serialized_size = _conversation_size_from_message_sizes(compacted_sizes)
    if serialized_size <= max_conversation_bytes:
        return compacted

    protected_indices = _required_message_indices(compacted)
    if compacted:
        protected_indices.add(len(compacted) - 1)
    retention_units = _conversation_retention_units(compacted)
    preferred_indices = {
        index
        for index, message in enumerate(compacted)
        if message.message_id in preferred_message_ids
    }
    retained = [True] * len(compacted)
    retained_count = len(compacted)
    removable_units = [
        unit
        for unit in retention_units
        if not protected_indices.intersection(unit)
        and not preferred_indices.intersection(unit)
    ]
    removable_units.extend(
        unit
        for unit in retention_units
        if not protected_indices.intersection(unit)
        and preferred_indices.intersection(unit)
    )
    for unit in removable_units:
        remaining_count = retained_count - len(unit)
        comma_bytes_removed = max(0, retained_count - 1) - max(0, remaining_count - 1)
        serialized_size -= sum(compacted_sizes[index] for index in unit)
        serialized_size -= comma_bytes_removed
        for index in unit:
            retained[index] = False
        retained_count = remaining_count
        if serialized_size <= max_conversation_bytes:
            return [
                message for index, message in enumerate(compacted) if retained[index]
            ]

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
    retention_units: list[list[int]],
    max_messages: int,
    tail_messages: int,
    preferred_message_ids: frozenset[str],
) -> list[ConversationMessage]:
    if len(conversation) <= max_messages:
        return list(conversation)

    required_indices = _required_message_indices(conversation)
    required_indices.add(len(conversation) - 1)
    tail_start = max(0, len(conversation) - tail_messages)
    required_units = [
        unit for unit in retention_units if required_indices.intersection(unit)
    ]
    required_count = sum(len(unit) for unit in required_units)
    if required_count > max_messages:
        raise ValueError(
            "Required AI Builder conversation context exceeds the message limit."
        )

    selected_unit_indices = {
        index
        for index, unit in enumerate(retention_units)
        if required_indices.intersection(unit)
    }
    selected_count = required_count

    def retain_latest_matching_units(
        predicate: Callable[[list[int]], bool],
    ) -> None:
        nonlocal selected_count
        for unit_index in range(len(retention_units) - 1, -1, -1):
            if unit_index in selected_unit_indices:
                continue
            unit = retention_units[unit_index]
            if not predicate(unit) or selected_count + len(unit) > max_messages:
                continue
            selected_unit_indices.add(unit_index)
            selected_count += len(unit)

    retain_latest_matching_units(
        lambda unit: any(
            conversation[index].message_id in preferred_message_ids for index in unit
        )
    )
    retain_latest_matching_units(lambda unit: unit[-1] >= tail_start)

    return [
        conversation[index]
        for unit_index, unit in enumerate(retention_units)
        if unit_index in selected_unit_indices
        for index in unit
    ]


def _conversation_retention_units(
    conversation: list[ConversationMessage],
) -> list[list[int]]:
    units: list[list[int]] = []
    index = 0
    while index < len(conversation):
        message = conversation[index]
        if message.role == "tool":
            raise ValueError(
                "AI Builder conversation contains an orphan or mismatched tool result."
            )

        unit = [index]
        calls = tool_calls_from_message(message)
        index += 1
        if message.role == "assistant" and calls:
            call_ids = tool_call_ids(calls)
            while index < len(conversation) and conversation[index].role == "tool":
                tool_result = conversation[index]
                if tool_result.tool_call_id not in call_ids:
                    raise ValueError(
                        "AI Builder conversation contains an orphan or mismatched "
                        "tool result."
                    )
                unit.append(index)
                index += 1
        units.append(unit)
    return units


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
    required_indices.update(_latest_question_interaction_indices(conversation))
    required_indices.update(_latest_tool_trace_indices(conversation))
    required_indices.update(_classifier_semantic_indices(conversation))
    return required_indices


def _retain_latest_classifier_semantics(
    conversation: list[ConversationMessage],
    *,
    compaction_limits: frozenset[Literal["count", "bytes"]],
) -> list[ConversationMessage]:
    selected_by_index: dict[int, frozenset[ClassifierRetentionIdentity]] = {}
    seen: set[ClassifierRetentionIdentity] = set()
    for index in range(len(conversation) - 1, -1, -1):
        classification = slot_classification_from_metadata(conversation[index].metadata)
        if classification is None:
            continue
        selected = classification.effective_retention_identities() - seen
        if selected:
            selected_by_index[index] = frozenset(selected)
            seen.update(selected)

    latest_selected_index = max(selected_by_index, default=None)
    retained: list[ConversationMessage] = []
    for index, message in enumerate(conversation):
        classification = slot_classification_from_metadata(message.metadata)
        if classification is None:
            retained.append(message)
            continue
        metadata = (
            dict(cast(Mapping[str, object], message.metadata))
            if isinstance(message.metadata, Mapping)
            else {}
        )
        metadata.pop(SLOT_CLASSIFICATION_METADATA_KEY, None)
        selected = selected_by_index.get(index)
        if selected:
            projected = classification.retain_effective_semantics(
                selected,
                compaction_limits=(
                    compaction_limits if index == latest_selected_index else frozenset()
                ),
            )
            metadata = (
                metadata_with_slot_classification(metadata, projected) or metadata
            )
        retained.append(message.model_copy(update={"metadata": metadata or None}))
    return retained


def _classifier_semantic_indices(
    conversation: list[ConversationMessage],
) -> Iterable[int]:
    return [
        index
        for index, message in enumerate(conversation)
        if (classification := slot_classification_from_metadata(message.metadata))
        is not None
        and classification.effective_retention_identities()
    ]


def _freeform_schema_candidate_message_ids(
    conversation: list[ConversationMessage],
) -> frozenset[str]:
    """Find replayable schema sources without making them unbounded invariants."""

    message_ids: set[str] = set()
    for message in conversation:
        try:
            candidates = derive_freeform_schema_candidates([message])
        except SchemaLimitExceeded as error:
            logger.warning(
                "AI Builder skipped unsafe schema evidence during conversation "
                "compaction",
                extra={
                    "message_id": message.message_id,
                    "reason": error.reason,
                    "max_value": error.max_value,
                    "actual_value": error.actual_value,
                },
            )
            continue
        if candidates:
            message_ids.add(message.message_id)
    return frozenset(message_ids)


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


def _latest_question_interaction_indices(
    conversation: list[ConversationMessage],
) -> Iterable[int]:
    latest_trace_by_question: dict[str, list[int]] = {}
    latest_by_question: dict[str, list[int]] = {}
    for index, message in enumerate(conversation):
        tool_calls = tool_calls_from_message(message)
        question_ids = {
            question_id
            for tool_call in tool_calls
            if tool_call.name == ASK_STRUCTURED_QUESTION_TOOL_NAME
            and isinstance(
                question_id := tool_call.arguments.get("question_id"),
                str,
            )
        }
        if message.role == "assistant" and question_ids:
            trace = [index]
            call_ids = tool_call_ids(tool_calls)
            cursor = index + 1
            while cursor < len(conversation):
                candidate = conversation[cursor]
                if candidate.role != "tool" or candidate.tool_call_id not in call_ids:
                    break
                trace.append(cursor)
                cursor += 1
            for question_id in question_ids:
                latest_trace_by_question[question_id] = trace
                latest_by_question[question_id] = trace
        if message.role != "user":
            continue
        question_id = question_interaction_id_from_metadata(message.metadata)
        if question_id is None:
            continue
        latest_by_question[question_id] = [
            *latest_trace_by_question.get(question_id, []),
            index,
        ]
    return sorted(
        {
            index
            for interaction_indices in latest_by_question.values()
            for index in interaction_indices
        }
    )


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
