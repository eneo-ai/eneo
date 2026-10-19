"""Generated images from MCP tools are persisted as files named by MIME type
and linked to the tool call that produced them."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import GeneratedFile
from eneo.assistants.assistant_service import (
    AssistantService,
    NonStreamingAnswer,
    _attach_generated_file_ids,
)
from eneo.files.file_models import File, FileType
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
    image = GeneratedFile(
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


def _skill_runtime_args() -> dict[str, object]:
    snapshot = SimpleNamespace(changed=False, measurement=SimpleNamespace(tokens=0))
    return {
        "skill_plan": SimpleNamespace(
            active_provenance=MagicMock(return_value=()),
            activation_evidence=MagicMock(
                return_value=SimpleNamespace(
                    effective_mode="selective", skill_context_tokens=0
                )
            ),
        ),
        "skill_runtime": SimpleNamespace(snapshot=MagicMock(return_value=snapshot)),
        "selected_model_route": "openai/gpt-4",
        "initial_skill_context_tokens": 0,
    }


async def test_non_streaming_answer_hands_back_the_files_its_tools_made():
    """A complete answer returns its saved files with the text, so the
    JSON response can list them as the stream and history do."""
    saved = File(
        id=uuid4(),
        name="generated_image.png",
        checksum="a1",
        size=4,
        blob=b"\x89PNG",
        mimetype="image/png",
        file_type=FileType.IMAGE,
        user_id=uuid4(),
        tenant_id=uuid4(),
    )
    service = AssistantService.__new__(AssistantService)
    service.user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)
    service.session_service = AsyncMock()
    service.file_service = AsyncMock()
    service.file_service.save_image_from_bytes = AsyncMock(return_value=saved)
    response = SimpleNamespace(
        completion=SimpleNamespace(
            text="Here is the chart.",
            mcp_tool_references=[],
            tool_calls_metadata=[],
            generated_images=[
                GeneratedFile(data=b"\x89PNG", mime_type="image/png", tool_call_id="c1")
            ],
            reasoning_content=None,
            output_token_estimate=3,
            context_input_token_estimate=None,
            context_output_token_estimate=None,
        ),
        total_token_count=5,
        usage=None,
        extended_logging=None,
    )

    answer = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
        service,
        response=response,  # pyright: ignore[reportArgumentType]
        datastore_result=SimpleNamespace(info_blobs=[], no_duplicate_chunks=[]),  # pyright: ignore[reportArgumentType]
        question="Chart it",
        files=[],
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),  # pyright: ignore[reportArgumentType]
        session=SimpleNamespace(id=uuid4(), questions=[]),  # pyright: ignore[reportArgumentType]
        stream=False,
        assistant_id=uuid4(),
        question_id=uuid4(),
        **_skill_runtime_args(),  # pyright: ignore[reportArgumentType]
    )

    assert isinstance(answer, NonStreamingAnswer)
    assert answer.text == "Here is the chart."
    assert answer.generated_files == (saved,)
    persisted = service.session_service.complete_question_with_answer.await_args
    assert persisted is not None
    assert persisted.kwargs["generated_files"] == [saved]
