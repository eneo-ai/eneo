"""History replay in ContextBuilder._build_messages.

Generated images (tool output) are replayed as vision input only from the
latest turn: that is where "change this image" follow-ups need them, while
older turns are already described to the model by the placeholder text in
their replayed tool results. Every replayed tool result additionally names a
fresh reference URL per generated image, so the model can pass any earlier
image back to an image tool. Uploaded images follow the vision gate as before.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.completion_models.infrastructure import context_builder
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.files.file_models import File, FileType
from eneo.questions.question import ToolCallInfo


def _image(name: str) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name=name,
        checksum="0",
        size=1,
        mimetype="image/png",
        file_type=FileType.IMAGE,
        blob=b"",
        user_id=uuid4(),
        tenant_id=uuid4(),
    )


def _turn(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        question=f"q{index}",
        answer=f"a{index}",
        files=[_image(f"upload{index}")],
        generated_files=[_image(f"generated{index}")],
        tool_calls=[],
    )


@pytest.fixture(autouse=True)
def _cheap_image_tokens(monkeypatch):
    monkeypatch.setattr(context_builder, "_image_files_tokens", lambda images, _m: 0)


def _names(files: list[File]) -> list[str]:
    return [file.name for file in files]


def test_generated_images_replay_only_from_latest_turn():
    session = SimpleNamespace(questions=[_turn(1), _turn(2), _turn(3)])

    messages, _ = ContextBuilder()._build_messages(session, max_tokens=10_000)

    assert [m.question for m in messages] == ["q1", "q2", "q3"]
    assert [_names(m.generated_images) for m in messages] == [[], [], ["generated3"]]
    # Uploaded images keep replaying from every turn.
    assert [_names(m.images) for m in messages] == [
        ["upload1"],
        ["upload2"],
        ["upload3"],
    ]


def test_no_images_replay_without_vision():
    session = SimpleNamespace(questions=[_turn(1), _turn(2)])

    messages, _ = ContextBuilder()._build_messages(
        session, max_tokens=10_000, vision=False
    )

    assert all(m.images == [] and m.generated_images == [] for m in messages)


def _image_tool_call(result: str, generated_file_ids) -> ToolCallInfo:
    return ToolCallInfo(
        server_name="image_generation",
        tool_name="generate_image",
        tool_call_id="call-1",
        result=result,
        mcp_tool_name="image_generation__generate_image",
        generated_file_ids=generated_file_ids,
    )


def test_replayed_tool_result_carries_a_reference_url_per_generated_image():
    first, second = uuid4(), uuid4()
    result = (
        "[Image 1 (image/png) was generated and is shown to the user.]\n"
        "[Image 2 (image/png) was generated and is shown to the user.]"
    )
    call = _image_tool_call(result, [first, second])
    session = SimpleNamespace(
        questions=[
            SimpleNamespace(
                question="q",
                answer="a",
                files=[],
                generated_files=[],
                tool_calls=[call],
            )
        ]
    )

    messages, _ = ContextBuilder()._build_messages(
        session,
        max_tokens=10_000,
        file_reference_urls={first: "https://x/1", second: "https://x/2"},
    )

    assert messages[0].tool_calls[0].result == (
        f"{result}\n"
        "Reference url for Image 1: https://x/1\n"
        "Reference url for Image 2: https://x/2"
    )
    # The persisted row is untouched: URLs are short-lived and replay-time only.
    assert call.result == result


def test_replayed_tool_result_is_unchanged_without_a_minted_url():
    result = "[Image 1 (image/png) was generated and is shown to the user.]"
    session = SimpleNamespace(
        questions=[
            SimpleNamespace(
                question="q",
                answer="a",
                files=[],
                generated_files=[],
                tool_calls=[_image_tool_call(result, [uuid4()])],
            )
        ]
    )

    messages, _ = ContextBuilder()._build_messages(session, max_tokens=10_000)

    assert messages[0].tool_calls[0].result == result
