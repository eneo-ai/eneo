"""Generated images from MCP tools are persisted as files named by MIME type."""

from unittest.mock import AsyncMock

import pytest

from eneo.ai_models.completion_models.completion_model import GeneratedImage
from eneo.assistants.assistant_service import AssistantService


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
