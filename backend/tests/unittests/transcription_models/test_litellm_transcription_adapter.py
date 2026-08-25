from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from litellm.exceptions import BadRequestError

from eneo.files.audio import AudioFile
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
    TranscriptionCallRequestFacts,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
)


class _CredentialResolverStub:
    provider_id = "provider-id"
    provider_type = "openai"

    def get_api_key(self, *, required: bool = False) -> str:
        return "test-key"

    def get_credential_field(self, *, field: str, required: bool = False) -> str | None:
        return None


@pytest.mark.parametrize(
    ("language", "expected_language"),
    [
        (None, "sv"),
        ("sv", "sv"),
        ("en", "en"),
    ],
)
@pytest.mark.asyncio
async def test_kb_whisper_language_fallback_only_when_language_is_auto(
    monkeypatch, tmp_path, language, expected_language
):
    captured_kwargs: dict[str, object] = {}

    async def fake_atranscription(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(text="transcript")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=fake_atranscription),
    )
    audio_path = tmp_path / "chunk.wav"
    audio_path.write_bytes(b"audio")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="KB Whisper", model_name="kb-whisper-large"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )

    result = await adapter._transcribe_chunk(
        audio_path, language=language, audio_seconds=1.0
    )

    assert result.text == "transcript"
    assert captured_kwargs["language"] == expected_language


class _Observer:
    """Stands in for the Flow provider-call recorder at the adapter boundary."""

    def __init__(self) -> None:
        self.started_requests: list[TranscriptionCallRequestFacts] = []
        self.completed_calls: list[UUID] = []
        self.rejected_calls: list[tuple[UUID, str]] = []
        self.unknown_calls: list[tuple[UUID, str]] = []

    async def started(self, request: TranscriptionCallRequestFacts) -> UUID:
        self.started_requests.append(request)
        return uuid4()

    async def completed(self, call_id: UUID, result: object) -> None:
        self.completed_calls.append(call_id)

    async def rejected(self, call_id: UUID, reason: str) -> None:
        self.rejected_calls.append((call_id, reason))

    async def outcome_unknown(self, call_id: UUID, reason: str) -> None:
        self.unknown_calls.append((call_id, reason))


@pytest.mark.asyncio
async def test_each_transcription_network_attempt_is_recorded_once(
    monkeypatch, tmp_path
):
    attempts = {"count": 0}

    async def flaky_atranscription(**kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("provider timed out")
        return SimpleNamespace(text="transcript", model="whisper-1", id="resp-2")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=flaky_atranscription),
    )
    audio_path = tmp_path / "chunk.wav"
    audio_path.write_bytes(b"audio bytes")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )
    observer = _Observer()

    result = await adapter._transcribe_chunk(
        audio_path, language="sv", observer=observer, audio_seconds=51.25
    )

    assert result.text == "transcript"
    # The retry is its own request, not a silent second charge folded into the
    # attempt it replaced.
    assert len(observer.started_requests) == 2
    assert [reason for _, reason in observer.unknown_calls] == ["provider_error"]
    assert len(observer.completed_calls) == 1
    assert {request.audio_seconds for request in observer.started_requests} == {51.25}
    # Same audio, same routing, so both attempts identify the same request.
    assert (
        observer.started_requests[0].provider_request_hash
        == observer.started_requests[1].provider_request_hash
    )


@pytest.mark.asyncio
async def test_failing_to_record_an_outcome_does_not_repeat_the_request(
    monkeypatch, tmp_path
):
    calls = {"count": 0}

    async def fake_atranscription(**kwargs):
        calls["count"] += 1
        return SimpleNamespace(text="transcript", model="whisper-1", id="resp-1")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=fake_atranscription),
    )
    audio_path = tmp_path / "chunk.wav"
    audio_path.write_bytes(b"audio bytes")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )

    class _BrokenObserver(_Observer):
        async def completed(self, call_id: UUID, result: object) -> None:
            raise ProviderCallObserverError("evidence store unavailable")

    with pytest.raises(ProviderCallObserverError):
        await adapter._transcribe_chunk(
            audio_path,
            language="sv",
            observer=_BrokenObserver(),
            audio_seconds=12.0,
        )

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_two_chunks_of_one_recording_are_different_requests(
    monkeypatch, tmp_path
):
    async def fake_atranscription(**kwargs):
        return SimpleNamespace(text="transcript", model="whisper-1", id="resp")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=fake_atranscription),
    )
    first = tmp_path / "first.wav"
    first.write_bytes(b"first chunk")
    second = tmp_path / "second.wav"
    second.write_bytes(b"second chunk")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )
    observer = _Observer()

    await adapter._transcribe_chunk(
        first, language="sv", observer=observer, audio_seconds=300.0
    )
    await adapter._transcribe_chunk(
        second, language="sv", observer=observer, audio_seconds=45.5
    )

    hashes = {request.provider_request_hash for request in observer.started_requests}
    assert len(hashes) == 2
    assert [request.audio_seconds for request in observer.started_requests] == [
        300.0,
        45.5,
    ]


def _write_wav(path: Path, *, seconds: float, samplerate: int = 8000) -> None:
    frames = int(seconds * samplerate)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(samplerate)
        handle.writeframes(b"\x00\x00" * frames)


@pytest.mark.asyncio
async def test_recorded_duration_is_the_audio_each_request_actually_sent(
    monkeypatch, tmp_path
):
    """The five-minute markers in the transcript are nominal; the rows are not.

    The splitter emits whole blocks and only checks the boundary after writing
    one, so an intermediate chunk overruns the interval its timestamp claims.
    Recording the interval would report a number the request never sent.
    """
    sent_durations: list[float] = []

    async def fake_atranscription(**kwargs):
        sent_file = kwargs["file"]
        sent_durations.append(AudioFile(sent_file.name).duration)
        return SimpleNamespace(text="transcript", model="whisper-1", id="resp")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=fake_atranscription),
    )
    source = tmp_path / "recording.wav"
    _write_wav(source, seconds=318.0)
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )
    observer = _Observer()

    await adapter.get_text_from_file(
        AudioFile(str(source)), language="sv", observer=observer
    )

    recorded = [request.audio_seconds for request in observer.started_requests]
    assert len(recorded) > 1
    # Every row is the file that request sent, measured.
    assert recorded == pytest.approx(sent_durations, abs=0.05)
    # And at least one emitted chunk is not the nominal five-minute interval its
    # transcript header claims, which is why the interval cannot be recorded.
    assert any(abs(seconds - 300.0) > 0.5 for seconds in recorded[:-1])


@pytest.mark.asyncio
async def test_a_refused_request_is_recorded_as_rejected_and_not_retried(
    monkeypatch, tmp_path
):
    calls = {"count": 0}

    async def refusing_atranscription(**kwargs):
        calls["count"] += 1
        raise BadRequestError(
            message="unsupported audio", model="whisper-1", llm_provider="openai"
        )

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm_transport.atranscription",
        AsyncMock(side_effect=refusing_atranscription),
    )
    audio_path = tmp_path / "chunk.wav"
    audio_path.write_bytes(b"audio bytes")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )
    observer = _Observer()

    with pytest.raises(ProviderRejectedRequestException):
        await adapter._transcribe_chunk(
            audio_path, language="sv", observer=observer, audio_seconds=12.0
        )

    assert calls["count"] == 1
    assert [reason for _, reason in observer.rejected_calls] == ["provider_rejected"]
    assert observer.unknown_calls == []
