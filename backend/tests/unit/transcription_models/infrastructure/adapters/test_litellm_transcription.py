"""Chunk windows from the LiteLLM transcription adapter."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from eneo.transcription_models.infrastructure.adapters import litellm_transcription
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
    TranscriptSegment,
)

TRANSPORT = (
    "eneo.transcription_models.infrastructure.adapters.litellm_transcription."
    "litellm_transport.atranscription"
)


class _CredentialResolverStub:
    provider_id = "provider-id"
    provider_type = "openai"

    def get_api_key(self, *, required: bool = False) -> str:
        return "test-key"

    def get_credential_field(self, *, field: str, required: bool = False) -> str | None:
        return None


class _Observer:
    def __init__(self) -> None:
        self.started_requests: list[object] = []
        self.completed_calls: list[UUID] = []
        self.rejected_reasons: list[str] = []

    async def started(self, request: object) -> UUID:
        self.started_requests.append(request)
        return uuid4()

    async def completed(self, call_id: UUID, result: object) -> None:
        self.completed_calls.append(call_id)

    async def rejected(self, call_id: UUID, reason: str) -> None:
        self.rejected_reasons.append(reason)

    async def outcome_unknown(self, call_id: UUID, reason: str) -> None:
        pass


def _adapter() -> LiteLLMTranscriptionAdapter:
    return LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="Whisper", model_name="whisper-1"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )


def _audio(tmp_path: Path, chunk_seconds: list[float], monkeypatch) -> SimpleNamespace:
    """A stand-in for AudioFile that splits into pre-measured chunks."""
    paths = []
    for index, seconds in enumerate(chunk_seconds):
        path = tmp_path / f"chunk-{index}.wav"
        path.write_bytes(f"chunk {index}".encode())
        paths.append(path)
    measured = {path: seconds for path, seconds in zip(paths, chunk_seconds)}
    monkeypatch.setattr(
        litellm_transcription, "_measure_seconds", lambda p: measured[p]
    )

    @asynccontextmanager
    async def asplit_file(*, seconds: int):
        yield paths

    return SimpleNamespace(duration=sum(chunk_seconds), asplit_file=asplit_file)


async def test_segments_are_the_measured_chunk_windows(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    texts = iter([" hej ", "du"])

    async def fake(**kwargs):
        calls.append(kwargs)
        # Provider timings are deliberately nonsense; they must not be used.
        return SimpleNamespace(
            text=next(texts),
            words=[{"word": "hej", "start": 0.0, "end": 900.0}],
            segments=[{"text": "hej", "start": 0.0, "end": 900.0}],
        )

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.7, 120.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    # Provider timestamps are never requested.
    assert all("response_format" not in call for call in calls)
    assert all("timestamp_granularities" not in call for call in calls)
    # Each chunk's window is placed by the measured lengths of the chunks
    # before it, not by the nominal five minutes the transcript header claims.
    assert result.segments == (
        TranscriptSegment("hej", 0.0, 300.7),
        TranscriptSegment("du", 300.7, 420.7),
    )
    assert result.text.startswith("### 0:00 - 5:00\n\n hej ")


async def test_silent_chunks_keep_their_place_but_emit_no_segment(
    monkeypatch, tmp_path
) -> None:
    texts = iter(["hej", "   ", "du"])

    async def fake(**kwargs):
        return SimpleNamespace(text=next(texts))

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.0, 300.0, 60.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert result.segments == (
        TranscriptSegment("hej", 0.0, 300.0),
        TranscriptSegment("du", 600.0, 660.0),
    )


async def test_transcript_with_no_text_has_no_segments(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(TRANSPORT, AsyncMock(return_value=SimpleNamespace(text="")))
    audio = _audio(tmp_path, [10.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert result.segments == ()
