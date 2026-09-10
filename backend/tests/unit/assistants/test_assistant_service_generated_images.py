"""Generated images from MCP tools are persisted as files named by MIME type
and linked to the tool call that produced them."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import GeneratedImage
from eneo.assistants.assistant_service import (
    AssistantService,
    _attach_generated_file_ids,
)
from eneo.questions.question import ToolCallInfo


def _service() -> AssistantService:
    service = AssistantService.__new__(AssistantService)
    service.file_service = AsyncMock()
    return service


@pytest.mark.parametrize(
    ("mime_type", "extension"),
    [
        ("image/png", "png"),
        ("image/jpeg", "jpeg"),
        ("image/webp", "webp"),
        ("image/gif", "gif"),
        ("IMAGE/PNG; charset=binary", "png"),
    ],
)
async def test_generated_image_is_saved_with_matching_extension(mime_type, extension):
    service = _service()
    image = GeneratedImage(
        data=b"\x89PNG", mime_type=mime_type, tool_call_id="c1", mcp_tool_name="t"
    )

    await service._save_generated_image(image)

    service.file_service.save_image_from_bytes.assert_awaited_once_with(
        b"\x89PNG", name=f"generated_image.{extension}", mimetype=mime_type
    )


def test_generated_file_ids_are_attached_to_their_tool_call():
    producing = ToolCallInfo(server_name="s", tool_name="t", tool_call_id="c1")
    other = ToolCallInfo(server_name="s", tool_name="t", tool_call_id="c2")
    pending = ToolCallInfo(server_name="s", tool_name="t", tool_call_id=None)
    first, second = uuid4(), uuid4()

    _attach_generated_file_ids(
        [producing, other, pending], {"c1": [first, second], "c9": [uuid4()]}
    )

    assert producing.generated_file_ids == [first, second]
    assert other.generated_file_ids is None
    assert pending.generated_file_ids is None
