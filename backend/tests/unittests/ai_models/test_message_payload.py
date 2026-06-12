import base64
import json
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import MessageToolCall
from intric.completion_models.infrastructure.message_payload import (
    build_content,
    build_image_block,
    build_turn_messages,
    countable_messages,
)
from intric.files.file_models import File, FileType

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000d4944415478da63f8cfc000000301010018dd8db00000000049"
    "454e44ae426082"
)


def _image_file(blob: bytes | None = _PNG_1PX) -> File:
    return File(
        id=uuid4(),
        name="photo.png",
        blob=blob,
        text="-" if blob is None else None,
        mimetype="image/png",
        checksum="",
        size=0,
        tenant_id=uuid4(),
        user_id=uuid4(),
        file_type=FileType.IMAGE,
    )


def test_build_image_block_encodes_blob_at_high_detail():
    block = build_image_block(_image_file())

    assert block["type"] == "image_url"
    assert block["image_url"]["detail"] == "high"
    expected_data = base64.b64encode(_PNG_1PX).decode("utf-8")
    assert block["image_url"]["url"] == f"data:image/png;base64,{expected_data}"


def test_build_image_block_raises_without_blob():
    with pytest.raises(ValueError):
        build_image_block(_image_file(blob=None))


def test_build_content_returns_plain_string_for_text_only():
    assert build_content("hello", []) == "hello"


def test_build_content_returns_blocks_with_images():
    content = build_content("hello", [_image_file()])

    assert isinstance(content, list)
    assert [block["type"] for block in content] == ["text", "image_url"]


_TOOL_CALL = MessageToolCall(
    tool_call_id="call_1",
    tool_name="time__get_current_time",
    arguments={"timezone": "Europe/Stockholm"},
    result="13:28",
)


def test_turn_without_tools_is_user_then_assistant():
    turn = build_turn_messages(question="Q", answer="A", images=[], tool_calls=[])

    assert turn == [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "A"},
    ]


def test_turn_with_tools_replays_canonical_openai_shape():
    turn = build_turn_messages(
        question="What time?", answer="13:28.", images=[], tool_calls=[_TOOL_CALL]
    )

    assert [m["role"] for m in turn] == ["user", "assistant", "tool", "assistant"]
    pre_tool = turn[1]
    assert pre_tool["content"] is None
    assert pre_tool["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "time__get_current_time",
                "arguments": json.dumps({"timezone": "Europe/Stockholm"}),
            },
        }
    ]
    assert turn[2] == {"role": "tool", "tool_call_id": "call_1", "content": "13:28"}
    assert turn[3] == {"role": "assistant", "content": "13:28."}


def test_countable_messages_serializes_tool_calls_and_none_content():
    turn = build_turn_messages(
        question="What time?", answer=None, images=[], tool_calls=[_TOOL_CALL]
    )

    countable = countable_messages(turn)

    assert all(isinstance(m["content"], str) for m in countable)
    assert "time__get_current_time" in countable[1]["content"]
    assert "Europe/Stockholm" in countable[1]["content"]
    assert countable[2] == {"role": "tool", "content": "13:28"}
