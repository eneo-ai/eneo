from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from intric.files.transcriber import Transcriber


@pytest.mark.asyncio
async def test_transcriber_uses_cache_for_auto_language():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="fresh-transcript")

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription="cached-transcript",
    )
    model = SimpleNamespace(name="whisper-1")

    result = await transcriber.transcribe(file, model, language=None)

    assert result == "cached-transcript"
    transcriber.transcribe_from_filepath.assert_not_awaited()
    file_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcriber_bypasses_cache_for_explicit_language():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="sv-transcript")

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription="cached-transcript",
    )
    model = SimpleNamespace(name="whisper-1")

    result = await transcriber.transcribe(file, model, language="sv")

    assert result == "sv-transcript"
    assert file.transcription == "sv-transcript"
    transcriber.transcribe_from_filepath.assert_awaited_once()
    file_repo.update.assert_awaited_once_with(file)


@pytest.mark.asyncio
async def test_transcriber_auto_language_without_cache_persists_result():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="new-transcript")

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription=None,
    )
    model = SimpleNamespace(name="whisper-1")

    result = await transcriber.transcribe(file, model, language=None)

    assert result == "new-transcript"
    transcriber.transcribe_from_filepath.assert_awaited_once()
    assert transcriber.transcribe_from_filepath.await_args.kwargs["language"] is None
    assert file.transcription == "new-transcript"
    file_repo.update.assert_awaited_once_with(file)


@pytest.mark.asyncio
async def test_transcriber_rejects_non_audio_files():
    transcriber = Transcriber(file_repo=AsyncMock())
    file = SimpleNamespace(
        blob=b"not-audio",
        mimetype="text/plain",
        transcription=None,
    )
    model = SimpleNamespace(name="whisper-1")

    with pytest.raises(ValueError, match="audio file"):
        await transcriber.transcribe(file, model, language=None)


@pytest.mark.asyncio
async def test_transcriber_auto_language_reuses_cache_even_if_model_changes():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="fresh-transcript")

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription="cached-transcript",
    )
    original_model = SimpleNamespace(name="whisper-1")
    different_model = SimpleNamespace(name="kb-whisper-large")

    first = await transcriber.transcribe(file, original_model, language=None)
    second = await transcriber.transcribe(file, different_model, language=None)

    assert first == "cached-transcript"
    assert second == "cached-transcript"
    transcriber.transcribe_from_filepath.assert_not_awaited()
    file_repo.update.assert_not_awaited()
