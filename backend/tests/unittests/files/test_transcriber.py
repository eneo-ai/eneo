from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eneo.files.transcriber import Transcriber


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
    assert file.transcription == "cached-transcript"
    transcriber.transcribe_from_filepath.assert_awaited_once()
    file_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcriber_auto_language_can_bypass_file_cache():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(return_value="fresh-transcript")

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription="cached-transcript",
    )
    model = SimpleNamespace(name="whisper-1")

    result = await transcriber.transcribe(
        file,
        model,
        language=None,
        persist_cache_to_file=False,
    )

    assert result == "fresh-transcript"
    assert file.transcription == "cached-transcript"
    transcriber.transcribe_from_filepath.assert_awaited_once()
    assert transcriber.transcribe_from_filepath.await_args.kwargs["language"] is None
    file_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcriber_explicit_language_does_not_fill_auto_cache():
    file_repo = AsyncMock()
    transcriber = Transcriber(file_repo=file_repo)
    transcriber.transcribe_from_filepath = AsyncMock(
        side_effect=["sv-transcript", "auto-transcript"]
    )

    file = SimpleNamespace(
        blob=b"audio-bytes",
        mimetype="audio/wav",
        transcription=None,
    )
    model = SimpleNamespace(name="whisper-1")

    explicit_result = await transcriber.transcribe(file, model, language="sv")
    auto_result = await transcriber.transcribe(file, model, language=None)

    assert explicit_result == "sv-transcript"
    assert auto_result == "auto-transcript"
    assert file.transcription == "auto-transcript"
    assert [
        call.kwargs["language"]
        for call in transcriber.transcribe_from_filepath.await_args_list
    ] == ["sv", None]
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


@pytest.mark.parametrize("language", ["sv", "en", None])
@pytest.mark.asyncio
async def test_transcribe_from_filepath_passes_language_to_adapter(
    monkeypatch, tmp_path, language
):
    transcriber = Transcriber(file_repo=AsyncMock())
    adapter = SimpleNamespace(get_text_from_file=AsyncMock(return_value="transcript"))
    transcriber._get_adapter = AsyncMock(return_value=adapter)
    wav_file = SimpleNamespace(name="converted.wav")

    @asynccontextmanager
    async def fake_to_wav(_filepath):
        yield wav_file

    monkeypatch.setattr("eneo.files.transcriber.audio.to_wav", fake_to_wav)

    result = await transcriber.transcribe_from_filepath(
        filepath=tmp_path / "input.wav",
        transcription_model=SimpleNamespace(name="whisper-1"),
        language=language,
    )

    assert result == "transcript"
    adapter.get_text_from_file.assert_awaited_once_with(wav_file, language=language)


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
