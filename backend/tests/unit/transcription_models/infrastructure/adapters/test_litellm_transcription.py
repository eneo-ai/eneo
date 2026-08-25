"""Word timestamps from the LiteLLM transcription adapter."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.main.exceptions import ProviderCapabilityRejectedException
from eneo.transcription_models.infrastructure.adapters import litellm_transcription
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
    TranscriptSegment,
    TranscriptWord,
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


async def test_word_timestamps_are_requested_and_offset_by_measured_chunks(
    monkeypatch, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            text="hej",
            words=[{"word": "hej", "start": 1.0, "end": 1.5}],
        )

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.7, 120.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio, want_words=True)  # type: ignore[arg-type]

    assert all(call["response_format"] == "verbose_json" for call in calls)
    assert all(call["timestamp_granularities"] == ["word", "segment"] for call in calls)
    assert result.timestamps_degraded is False
    # The second chunk's words are shifted by the first chunk's measured length,
    # not by the nominal five minutes the transcript header claims.
    assert result.words == (
        TranscriptWord("hej", 1.0, 1.5),
        TranscriptWord("hej", 301.7, 302.2),
    )
    assert result.text.startswith("### 0:00 - 5:00")


async def test_without_word_request_no_timestamp_parameters_are_sent(
    monkeypatch, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            text="hej", words=[{"word": "hej", "start": 0, "end": 1}]
        )

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [10.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio)  # type: ignore[arg-type]

    assert "response_format" not in calls[0]
    assert result.words is None
    assert result.timestamps_degraded is False


async def test_provider_rejecting_timestamps_degrades_to_text_only(
    monkeypatch, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    async def fake(**kwargs):
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise ProviderCapabilityRejectedException(
                "no", capability="response_format", retry_without_capability_safe=False
            )
        return SimpleNamespace(text="hej")

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [10.0, 10.0], monkeypatch)
    observer = _Observer()

    result = await _adapter().get_text_from_file(
        audio,  # type: ignore[arg-type]
        want_words=True,
        observer=observer,  # type: ignore[arg-type]
    )

    # First chunk: refused with timestamps, retried without; second chunk never asks.
    assert [("response_format" in call) for call in calls] == [True, False, False]
    assert result.words is None
    assert result.timestamps_degraded is True
    assert result.text.count("hej") == 2
    # The refused attempt is recorded as a rejection, the retries as completions.
    assert observer.rejected_reasons == ["provider_rejected"]
    assert len(observer.completed_calls) == 2


async def test_provider_returning_no_timestamps_degrades(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        TRANSPORT, AsyncMock(return_value=SimpleNamespace(text="hej", words=[]))
    )
    audio = _audio(tmp_path, [10.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio, want_words=True)  # type: ignore[arg-type]

    assert result.words is None
    assert result.segments is None
    assert result.timestamps_degraded is True


async def test_segments_survive_when_words_are_missing(monkeypatch, tmp_path) -> None:
    async def fake(**kwargs):
        return SimpleNamespace(
            text="hej du",
            segments=[{"text": " hej du ", "start": 0.5, "end": 1.2}],
        )

    monkeypatch.setattr(TRANSPORT, AsyncMock(side_effect=fake))
    audio = _audio(tmp_path, [300.7, 10.0], monkeypatch)

    result = await _adapter().get_text_from_file(audio, want_words=True)  # type: ignore[arg-type]

    assert result.words is None
    assert result.timestamps_degraded is False
    assert result.segments == (
        TranscriptSegment("hej du", 0.5, 1.2),
        TranscriptSegment("hej du", 301.2, 301.9),
    )


@pytest.mark.parametrize(
    "raw",
    [
        [{"word": "hej", "start": "0", "end": 1}],
        [{"word": None, "start": 0, "end": 1}],
        "not a list",
    ],
)
def test_malformed_word_payloads_are_treated_as_absent(raw: object) -> None:
    assert litellm_transcription._extract_words(SimpleNamespace(words=raw)) is None
