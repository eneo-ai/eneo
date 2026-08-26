from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.diarizing_transcription import (
    DIARIZATION_SKIPPED_NO_WORD_TIMESTAMPS,
    DiarizingFlowTranscriber,
)
from eneo.flows.runtime.remote_transcription import RemoteTranscriptionResult
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
    TranscriptWord,
)

WORDS = (TranscriptWord("hej", 0.0, 0.4), TranscriptWord("du", 0.5, 0.7))
MODEL = SimpleNamespace(name="Whisper", model_name="whisper-1")
FILE = SimpleNamespace(name="meeting.mp3", mimetype="audio/mpeg", blob=b"x")


def _registry(transcribed: TranscribedAudio) -> SimpleNamespace:
    return SimpleNamespace(transcribe=AsyncMock(return_value=transcribed))


def _remote(text: str = "[00:00:00 - 00:00:01] SPEAKER_00: hej du") -> SimpleNamespace:
    return SimpleNamespace(
        label_speakers=AsyncMock(
            return_value=RemoteTranscriptionResult(
                text=text, duration_seconds=1.0, model="whisper-1", language="sv"
            )
        )
    )


async def test_registry_transcribes_and_service_labels_speakers() -> None:
    registry = _registry(TranscribedAudio("hej du", 30.0, words=WORDS))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(  # type: ignore[arg-type]
        FILE, MODEL, language="sv", diarize=True, max_speakers=2
    )

    assert result.text.startswith("[00:00:00 - 00:00:01] SPEAKER_00:")
    # Usage comes from the registry transcription; the service is not a second charge.
    assert result.duration_seconds == 30.0
    assert result.diarization == "external"
    assert result.diarization_elapsed_ms is not None
    registry.transcribe.assert_awaited_once()
    assert registry.transcribe.await_args.kwargs["want_words"] is True
    assert registry.transcribe.await_args.kwargs["persist_cache_to_file"] is False
    remote.label_speakers.assert_awaited_once()
    assert remote.label_speakers.await_args.kwargs["words"] == WORDS
    assert remote.label_speakers.await_args.kwargs["max_speakers"] == 2
    assert remote.label_speakers.await_args.kwargs["model_name"] == "whisper-1"


async def test_speaker_identification_off_never_calls_the_service() -> None:
    registry = _registry(TranscribedAudio("hej du", 30.0))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(FILE, MODEL, diarize=False)  # type: ignore[arg-type]

    assert result.text == "hej du"
    assert result.diarization is None
    assert registry.transcribe.await_args.kwargs["want_words"] is False
    remote.label_speakers.assert_not_awaited()


async def test_segment_timestamps_are_enough_to_label_speakers() -> None:
    segments = (TranscriptSegment("hej du", 0.0, 0.7),)
    registry = _registry(
        TranscribedAudio("hej du", 30.0, words=None, segments=segments)
    )
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(FILE, MODEL, diarize=True)  # type: ignore[arg-type]

    assert result.diarization == "external"
    assert remote.label_speakers.await_args.kwargs["words"] is None
    assert remote.label_speakers.await_args.kwargs["segments"] == segments


async def test_missing_word_timestamps_skip_labelling_instead_of_failing() -> None:
    registry = _registry(TranscribedAudio("hej du", 30.0, words=None))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(FILE, MODEL, diarize=True)  # type: ignore[arg-type]

    assert result.text == "hej du"
    assert result.diarization == DIARIZATION_SKIPPED_NO_WORD_TIMESTAMPS
    remote.label_speakers.assert_not_awaited()


async def test_service_failure_after_transcription_fails_the_call() -> None:
    registry = _registry(TranscribedAudio("hej du", 30.0, words=WORDS))
    remote = SimpleNamespace(
        label_speakers=AsyncMock(
            side_effect=ProviderRejectedRequestException("refused", code="x")
        )
    )
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    with pytest.raises(ProviderRejectedRequestException):
        await transcriber.transcribe(FILE, MODEL, diarize=True)  # type: ignore[arg-type]
