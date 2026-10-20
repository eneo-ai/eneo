"""An audio upload reaches the model as its transcript: the ask path
transcribes each one with the space's transcription model before the turn
runs, and keeps a transcript the file already has."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.assistants.assistant_service import AssistantService
from eneo.files.file_models import File, FileType
from eneo.main.exceptions import BadRequestException


def _service(transcriber: MagicMock | None) -> AssistantService:
    service = AssistantService.__new__(AssistantService)
    service.transcriber = transcriber
    return service


def _file(file_type: FileType, **content: object) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="upload",
        checksum="0",
        size=1,
        mimetype="audio/mpeg" if file_type is FileType.AUDIO else "text/plain",
        file_type=file_type,
        user_id=uuid4(),
        tenant_id=uuid4(),
        **content,
    )


def _space(transcription_model: object | None) -> MagicMock:
    space = MagicMock()
    space.get_default_transcription_model.return_value = transcription_model
    return space


async def test_pending_audio_is_transcribed_with_the_space_model() -> None:
    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(return_value="Hej allihop")
    model = MagicMock()
    pending = _file(FileType.AUDIO, blob=b"mp3")
    done = _file(FileType.AUDIO, blob=b"mp3", transcription="Redan klar")
    document = _file(FileType.TEXT, text="a note")

    await _service(transcriber)._transcribe_audio_attachments(
        files=[pending, done, document], space=_space(model)
    )

    transcriber.transcribe.assert_awaited_once_with(pending, model)
    assert pending.transcription == "Hej allihop"
    assert done.transcription == "Redan klar"


async def test_audio_without_a_transcription_model_is_rejected() -> None:
    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock()

    with pytest.raises(BadRequestException, match="transcription model"):
        await _service(transcriber)._transcribe_audio_attachments(
            files=[_file(FileType.AUDIO, blob=b"mp3")], space=_space(None)
        )

    transcriber.transcribe.assert_not_awaited()


async def test_a_turn_without_pending_audio_asks_for_no_model() -> None:
    space = _space(MagicMock())

    await _service(None)._transcribe_audio_attachments(
        files=[
            _file(FileType.TEXT, text="a note"),
            _file(FileType.AUDIO, blob=b"mp3", transcription="Redan klar"),
        ],
        space=space,
    )

    space.get_default_transcription_model.assert_not_called()
