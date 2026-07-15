from __future__ import annotations

from unittest.mock import patch

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_CONVERSATION_BYTES,
    MAX_SESSION_MESSAGE_BYTES,
    compact_ai_builder_conversation,
    conversation_serialized_size_bytes,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_edit_scope import build_active_request_window
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    extract_freeform_user_messages,
)
from eneo.flows.ai_builder.ai_builder_interaction_utils import analyze_discovery_ready
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    conversation_message_to_llm_message,
)


def _msg(
    role: str,
    *,
    content: str = "",
    metadata: dict | None = None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        role=role,
        content=content,
        metadata=metadata,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )


def test_compaction_keeps_latest_requirements_summary_even_if_old() -> None:
    conversation = [_msg("user", content=f"msg {i}") for i in range(50)]
    conversation.insert(
        5,
        _msg(
            "assistant",
            content="confirm requirements",
            tool_calls=[
                {
                    "id": "call-requirements",
                    "name": "confirm_requirements",
                    "arguments": {},
                }
            ],
        ),
    )
    conversation.insert(
        6,
        _msg(
            "tool",
            content="requirements",
            tool_call_id="call-requirements",
            metadata={
                "requirements_summary": {"summary": "x"},
                "requirements_version": "req-v1",
            },
        ),
    )
    conversation.insert(
        7,
        _msg(
            "user",
            content="confirmed",
            metadata={"requirements_confirmed": True, "requirements_version": "req-v1"},
        ),
    )

    compacted = compact_ai_builder_conversation(
        conversation, max_messages=20, tail_messages=10
    )

    assert any(
        isinstance(msg.metadata, dict) and msg.metadata.get("requirements_summary")
        for msg in compacted
    )
    assert any(
        isinstance(msg.metadata, dict)
        and msg.metadata.get("requirements_confirmed") is True
        for msg in compacted
    )


def test_compaction_keeps_latest_tool_trace_pair() -> None:
    conversation = [_msg("user", content=f"msg {i}") for i in range(30)]
    conversation.extend(
        [
            _msg(
                "assistant",
                content="plan",
                tool_calls=[{"id": "call-1", "name": "propose_flow", "arguments": {}}],
            ),
            _msg("tool", content="plan summary", tool_call_id="call-1"),
        ]
    )
    conversation.extend([_msg("user", content=f"tail {i}") for i in range(30)])

    compacted = compact_ai_builder_conversation(
        conversation, max_messages=25, tail_messages=10
    )

    assert any(msg.tool_calls for msg in compacted)
    assert any(msg.tool_call_id == "call-1" for msg in compacted)


def test_compaction_preserves_tool_trace_atomically_after_final_slice() -> None:
    conversation = [_msg("user", content=f"msg {i}") for i in range(70)]
    conversation.insert(
        10,
        _msg(
            "assistant",
            content="plan",
            tool_calls=[{"id": "call-42", "name": "propose_flow", "arguments": {}}],
        ),
    )
    conversation.insert(11, _msg("tool", content="summary", tool_call_id="call-42"))

    compacted = compact_ai_builder_conversation(
        conversation, max_messages=20, tail_messages=20
    )

    assert any(msg.tool_calls for msg in compacted)
    assert any(msg.tool_call_id == "call-42" for msg in compacted)


def test_compaction_preserves_structured_answers_needed_for_discovery_soft_bypass() -> (
    None
):
    conversation = []
    for i in range(4):
        conversation.append(
            _msg(
                "user",
                content=f"answer {i}",
                metadata={
                    "question_answer": {
                        "question_id": f"q{i}",
                        "selected_value": f"answer-{i}",
                    }
                },
            )
        )
    conversation.extend(_msg("user", content=f"tail {i}") for i in range(70))

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_interaction_utils.build_discovery_block_message",
        return_value="still blocked",
    ):
        assert analyze_discovery_ready(compacted) is True


def test_compaction_preserves_latest_user_request_before_requirements_confirmation() -> (
    None
):
    conversation = [_msg("user", content=f"filler {i}") for i in range(45)]
    conversation.extend(
        [
            _msg(
                "user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
            ),
            _msg(
                "assistant",
                content="Jag förstår att du vill byta slutresultatet från PDF till DOCX.",
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": "confirm_requirements",
                        "arguments": {
                            "summary": "Byt slutformat till DOCX.",
                            "key_decisions": [],
                            "input_description": "Ljudfil.",
                            "output_description": "DOCX.",
                        },
                    }
                ],
            ),
            _msg(
                "tool",
                content="Requirements summary recorded.",
                tool_call_id="call_requirements",
                metadata={
                    "requirements_summary": {"summary": "Byt slutformat till DOCX."},
                    "requirements_version": "req-v1",
                },
            ),
            _msg(
                "user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "req-v1",
                },
            ),
        ]
    )
    conversation.extend(_msg("assistant", content=f"tail {i}") for i in range(30))

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )
    request_window = build_active_request_window(compacted, flow_defaults={})

    assert "word dokument istället för en pdf" in request_window.text
    assert "ja, det stämmer. bygg planen." in request_window.text
    assert extract_freeform_user_messages(compacted)


def test_compaction_skips_structured_answer_echo_when_preserving_latest_user_request() -> (
    None
):
    conversation = [_msg("user", content=f"filler {i}") for i in range(45)]
    conversation.extend(
        [
            _msg(
                "user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
            ),
            _msg(
                "user",
                content="pdf_document",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_value": "pdf_document",
                    }
                },
            ),
            _msg(
                "assistant",
                content="Jag förstår att du vill byta slutresultatet från PDF till DOCX.",
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": "confirm_requirements",
                        "arguments": {
                            "summary": "Byt slutformat till DOCX.",
                            "key_decisions": [],
                            "input_description": "Ljudfil.",
                            "output_description": "DOCX.",
                        },
                    }
                ],
            ),
            _msg(
                "tool",
                content="Requirements summary recorded.",
                tool_call_id="call_requirements",
                metadata={
                    "requirements_summary": {"summary": "Byt slutformat till DOCX."},
                    "requirements_version": "req-v1",
                },
            ),
            _msg(
                "user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "req-v1",
                },
            ),
        ]
    )
    conversation.extend(_msg("assistant", content=f"tail {i}") for i in range(30))

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )
    request_window = build_active_request_window(compacted, flow_defaults={})

    assert "word dokument istället för en pdf" in request_window.text
    assert "pdf_document" not in request_window.text


def test_compaction_skips_structured_answer_echo_with_terminal_punctuation() -> None:
    conversation = [_msg("user", content=f"filler {i}") for i in range(45)]
    conversation.extend(
        [
            _msg(
                "user",
                content="pdf_document.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_value": "pdf_document",
                    }
                },
            ),
            _msg(
                "user",
                content="Behåll samma flöde men lägg till källor också.",
            ),
        ]
    )

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )
    request_window = build_active_request_window(compacted, flow_defaults={})

    assert "pdf_document." not in request_window.text
    assert "lägg till källor också" in request_window.text


def test_compaction_preserves_latest_freeform_request_even_if_question_answer_metadata_exists() -> (
    None
):
    conversation = [_msg("user", content=f"filler {i}") for i in range(45)]
    conversation.extend(
        [
            _msg(
                "user",
                content="ändra så att slutresultatet blir mer formellt och lättare att läsa",
                metadata={
                    "question_answer": {
                        "question_id": "output_style",
                        "selected_value": "formal",
                    }
                },
            ),
            _msg(
                "assistant",
                content="Jag förstår att du vill justera stil och ton.",
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": "confirm_requirements",
                        "arguments": {
                            "summary": "Justera stil och ton i utdata.",
                            "key_decisions": [],
                            "input_description": "Samma indata.",
                            "output_description": "Mer formell text.",
                        },
                    }
                ],
            ),
            _msg(
                "tool",
                content="Requirements summary recorded.",
                tool_call_id="call_requirements",
                metadata={
                    "requirements_summary": {
                        "summary": "Justera stil och ton i utdata."
                    },
                    "requirements_version": "req-v2",
                },
            ),
            _msg(
                "user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "req-v2",
                },
            ),
        ]
    )
    conversation.extend(_msg("assistant", content=f"tail {i}") for i in range(30))

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )
    request_window = build_active_request_window(compacted, flow_defaults={})

    assert "mer formellt och lättare att läsa" in request_window.text


def test_compaction_deduplicates_structured_answers_by_canonical_question_id() -> None:
    conversation = [
        _msg(
            "user",
            content="old answer",
            metadata={
                "question_answer": {
                    "question_id": "final_output_format",
                    "selected_value": "pdf_document",
                }
            },
        ),
        _msg(
            "user",
            content="new answer",
            metadata={
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_value": "docx_document",
                }
            },
        ),
    ]
    conversation.extend(_msg("assistant", content=f"tail {i}") for i in range(80))

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=20,
        tail_messages=10,
    )

    preserved_answers = [
        msg
        for msg in compacted
        if isinstance(msg.metadata, dict)
        and isinstance(msg.metadata.get("question_answer"), dict)
    ]
    assert len(preserved_answers) == 1
    assert preserved_answers[0].content == "new answer"


def test_compaction_accepts_exact_per_message_serialized_byte_cap() -> None:
    message = _msg("user")
    fixed_bytes = conversation_serialized_size_bytes([message]) - 2
    message = message.model_copy(
        update={"content": "x" * (MAX_SESSION_MESSAGE_BYTES - fixed_bytes)}
    )

    compacted = compact_ai_builder_conversation([message])

    assert conversation_serialized_size_bytes(compacted) == (
        MAX_SESSION_MESSAGE_BYTES + 2
    )


def test_compaction_rejects_per_message_serialized_byte_cap_plus_one() -> None:
    message = _msg("user")
    fixed_bytes = conversation_serialized_size_bytes([message]) - 2
    oversized = message.model_copy(
        update={"content": "x" * (MAX_SESSION_MESSAGE_BYTES - fixed_bytes + 1)}
    )

    with pytest.raises(ValueError, match="serialized byte limit"):
        compact_ai_builder_conversation([oversized])


def test_compaction_accepts_exact_total_and_compacts_maximum_plus_one() -> None:
    messages = [_msg("user") for _index in range(5)]
    fixed_bytes = conversation_serialized_size_bytes(messages)
    content_budget = MAX_SESSION_CONVERSATION_BYTES - fixed_bytes
    content_sizes = [content_budget // len(messages)] * len(messages)
    content_sizes[-1] += content_budget - sum(content_sizes)
    at_limit = [
        message.model_copy(update={"content": "x" * content_size})
        for message, content_size in zip(messages, content_sizes, strict=True)
    ]

    assert conversation_serialized_size_bytes(at_limit) == (
        MAX_SESSION_CONVERSATION_BYTES
    )
    assert compact_ai_builder_conversation(at_limit) == at_limit

    over_limit = [
        at_limit[0].model_copy(update={"content": f"{at_limit[0].content}x"}),
        *at_limit[1:],
    ]
    compacted = compact_ai_builder_conversation(over_limit)

    assert compacted == at_limit[1:]
    assert (
        conversation_serialized_size_bytes(compacted) <= MAX_SESSION_CONVERSATION_BYTES
    )


def test_byte_compaction_drops_complete_older_tool_group() -> None:
    older_group = [
        _msg(
            "assistant",
            content="older call",
            tool_calls=[{"id": "call-old", "name": "older", "arguments": {}}],
        ),
        _msg("tool", content="older result", tool_call_id="call-old"),
    ]
    newer_group = [
        _msg(
            "assistant",
            content="newer call",
            tool_calls=[{"id": "call-new", "name": "newer", "arguments": {}}],
        ),
        _msg("tool", content="newer result", tool_call_id="call-new"),
    ]
    final_message = _msg("user", content="continue")
    conversation = [*older_group, *newer_group, final_message]
    orphan_boundary = conversation_serialized_size_bytes(conversation[1:])

    compacted = compact_ai_builder_conversation(
        conversation,
        max_conversation_bytes=orphan_boundary,
    )

    assert compacted == [*newer_group, final_message]
    assert conversation_serialized_size_bytes(compacted) <= orphan_boundary

    provider_messages = [
        conversation_message_to_llm_message(message) for message in compacted
    ]
    assert [message["role"] for message in provider_messages] == [
        "assistant",
        "tool",
        "user",
    ]
    assert provider_messages[1]["tool_call_id"] == "call-new"


def test_byte_compaction_accepts_exact_multibyte_total_and_drops_group_at_plus_one() -> (
    None
):
    older_group = [
        _msg(
            "assistant",
            content="äldre anrop 🧰",
            tool_calls=[{"id": "call-old", "name": "older", "arguments": {}}],
        ),
        _msg("tool", content="äldre resultat ✅", tool_call_id="call-old"),
    ]
    newer_group = [
        _msg(
            "assistant",
            content="newer call",
            tool_calls=[{"id": "call-new", "name": "newer", "arguments": {}}],
        ),
        _msg("tool", content="newer result", tool_call_id="call-new"),
    ]
    final_message = _msg("user", content="continue")
    conversation = [*older_group, *newer_group, final_message]
    exact_size = conversation_serialized_size_bytes(conversation)

    assert (
        compact_ai_builder_conversation(
            conversation,
            max_conversation_bytes=exact_size,
        )
        == conversation
    )
    assert compact_ai_builder_conversation(
        conversation,
        max_conversation_bytes=exact_size - 1,
    ) == [*newer_group, final_message]


def test_count_compaction_keeps_tool_group_crossing_tail_boundary() -> None:
    tool_group = [
        _msg(
            "assistant",
            content="boundary call",
            tool_calls=[{"id": "call-boundary", "name": "boundary", "arguments": {}}],
        ),
        _msg("tool", content="boundary result", tool_call_id="call-boundary"),
    ]
    final_messages = [
        _msg("assistant", content="latest explanation"),
        _msg("user", content="continue"),
    ]
    conversation = [
        _msg("user", content="drop 0"),
        _msg("user", content="drop 1"),
        *tool_group,
        *final_messages,
    ]

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=4,
        tail_messages=3,
    )

    assert compacted == [*tool_group, *final_messages]


def test_count_compaction_preserves_duplicate_retained_messages() -> None:
    duplicate = _msg("user", content="same retained message")
    final_message = _msg("assistant", content="latest response")
    conversation = [
        _msg("user", content="drop 0"),
        _msg("user", content="drop 1"),
        duplicate,
        duplicate,
        final_message,
    ]

    compacted = compact_ai_builder_conversation(
        conversation,
        max_messages=3,
        tail_messages=3,
    )

    assert compacted == [duplicate, duplicate, final_message]


@pytest.mark.parametrize(
    "conversation",
    [
        [_msg("tool", content="orphan", tool_call_id="call-orphan")],
        [
            _msg(
                "assistant",
                content="call",
                tool_calls=[{"id": "call-a", "name": "tool", "arguments": {}}],
            ),
            _msg("tool", content="mismatch", tool_call_id="call-b"),
        ],
    ],
)
def test_compaction_rejects_orphan_and_mismatched_tool_results(
    conversation: list[ConversationMessage],
) -> None:
    with pytest.raises(ValueError, match="orphan or mismatched tool result"):
        compact_ai_builder_conversation(conversation)


def test_count_compaction_rejects_required_complete_group_overflow() -> None:
    required_group = [
        _msg(
            "assistant",
            content="required call",
            tool_calls=[{"id": "call-required", "name": "tool", "arguments": {}}],
        ),
        _msg("tool", content="required result", tool_call_id="call-required"),
    ]

    with pytest.raises(ValueError, match="exceeds the message limit"):
        compact_ai_builder_conversation(
            required_group,
            max_messages=1,
            tail_messages=1,
        )


def test_byte_compaction_rejects_required_complete_group_overflow() -> None:
    required_group = [
        _msg(
            "assistant",
            content="required call",
            tool_calls=[{"id": "call-required", "name": "tool", "arguments": {}}],
        ),
        _msg("tool", content="required result", tool_call_id="call-required"),
    ]
    required_size = conversation_serialized_size_bytes(required_group)

    with pytest.raises(ValueError, match="exceeds the serialized byte limit"):
        compact_ai_builder_conversation(
            required_group,
            max_conversation_bytes=required_size - 1,
        )


def test_compaction_enforces_utf8_bytes_instead_of_character_count() -> None:
    message = _msg("user")
    fixed_bytes = conversation_serialized_size_bytes([message]) - 2
    unicode_characters = (MAX_SESSION_MESSAGE_BYTES - fixed_bytes) // 2 + 1
    oversized = message.model_copy(update={"content": "å" * unicode_characters})

    with pytest.raises(ValueError, match="serialized byte limit"):
        compact_ai_builder_conversation([oversized])
