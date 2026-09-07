"""History replay in ContextBuilder._build_messages.

Generated images (tool output) are replayed only from the latest turn: that
is where "change this image" follow-ups need them, while older turns are
already described to the model by the placeholder text in their replayed
tool results. Uploaded images follow the vision gate as before.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.completion_models.infrastructure import context_builder
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.files.file_models import File, FileType


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
