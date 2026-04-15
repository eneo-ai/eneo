from __future__ import annotations

from intric.flows.ai_builder.ai_builder_conversation_compaction import (
    compact_ai_builder_conversation,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage


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
            "tool",
            content="requirements",
            metadata={
                "requirements_summary": {"summary": "x"},
                "requirements_version": "req-v1",
            },
        ),
    )
    conversation.insert(
        6,
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
                tool_calls=[{"id": "call-1", "name": "create_flow", "arguments": {}}],
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
            tool_calls=[{"id": "call-42", "name": "create_flow", "arguments": {}}],
        ),
    )
    conversation.insert(11, _msg("tool", content="summary", tool_call_id="call-42"))

    compacted = compact_ai_builder_conversation(
        conversation, max_messages=20, tail_messages=20
    )

    assert any(msg.tool_calls for msg in compacted)
    assert any(msg.tool_call_id == "call-42" for msg in compacted)
