from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.diarizing_transcription import (
    DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT,
    DiarizingFlowTranscriber,
)
from eneo.flows.runtime.remote_transcription import RemoteTranscriptionResult
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    EmptyTranscriptionInterval,
    TranscriptSegment,
)
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract

SEGMENTS = (
    TranscriptSegment("hej du", 0.0, 300.7),
    TranscriptSegment("hej igen", 300.7, 420.7),
)
MODEL = SimpleNamespace(name="Whisper", model_name="whisper-1")
FILE = SimpleNamespace(id=uuid4(), name="meeting.mp3", mimetype="audio/mpeg", blob=b"x")


def _registry(transcribed: TranscribedAudio) -> SimpleNamespace:
    return SimpleNamespace(transcribe_from_filepath=AsyncMock(return_value=transcribed))


def _remote(text: str = "[00:00:00 - 00:00:01] SPEAKER_00: hej du") -> SimpleNamespace:
    return SimpleNamespace(
        label_speakers=AsyncMock(
            return_value=RemoteTranscriptionResult(
                text=text,
                duration_seconds=1.0,
                model="whisper-1",
                language="sv",
                alignment="forced",
                segments=(TranscriptSegment("hej du", 0.0, 1.0, speaker="SPEAKER_00"),),
            )
        )
    )


async def test_registry_transcribes_and_service_labels_speakers(spool_contract) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    empty_intervals = (EmptyTranscriptionInterval(300.7, 601.4),)
    registry = _registry(
        TranscribedAudio(
            "hej du", 30.0, segments=SEGMENTS, empty_intervals=empty_intervals
        )
    )
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(  # type: ignore[arg-type]
        spool, MODEL, file_id=FILE.id, language="sv", diarize=True, max_speakers=2
    )

    assert result.text.startswith("[00:00:00 - 00:00:01] SPEAKER_00:")
    # Usage comes from the registry transcription; the service is not a second charge.
    assert result.duration_seconds == 30.0
    assert result.diarization == "external"
    assert result.diarization_elapsed_ms is not None
    assert result.alignment == "forced"
    # Chunk windows stay what Eneo measured; the reader's segments are the
    # service's labelled lines.
    assert result.segments == SEGMENTS
    assert result.empty_intervals == empty_intervals
    assert result.transcript_segments == (
        TranscriptSegment("hej du", 0.0, 1.0, speaker="SPEAKER_00"),
    )
    registry.transcribe_from_filepath.assert_awaited_once()
    assert registry.transcribe_from_filepath.await_args.kwargs["filepath"] == spool.path
    remote.label_speakers.assert_awaited_once()
    assert remote.label_speakers.await_args.kwargs["max_speakers"] == 2
    assert remote.label_speakers.await_args.kwargs["model_name"] == "whisper-1"


async def test_service_gets_chunk_windows_and_never_provider_words(
    spool_contract,
) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    registry = _registry(TranscribedAudio("hej du", 30.0, segments=SEGMENTS))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=True)  # type: ignore[arg-type]

    assert remote.label_speakers.await_args.kwargs["words"] is None
    assert remote.label_speakers.await_args.kwargs["segments"] == SEGMENTS


async def test_speaker_identification_off_never_calls_the_service(
    spool_contract,
) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    registry = _registry(TranscribedAudio("hej du", 30.0, segments=SEGMENTS))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=False)  # type: ignore[arg-type]

    assert result.text == "hej du"
    assert result.diarization is None
    remote.label_speakers.assert_not_awaited()


async def test_empty_transcript_skips_labelling_instead_of_failing(
    spool_contract,
) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    registry = _registry(TranscribedAudio("", 30.0, segments=()))
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=True)  # type: ignore[arg-type]

    assert result.text == ""
    assert result.diarization == DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT
    remote.label_speakers.assert_not_awaited()


async def test_service_failure_after_transcription_fails_the_call(
    spool_contract,
) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    registry = _registry(TranscribedAudio("hej du", 30.0, segments=SEGMENTS))
    remote = SimpleNamespace(
        label_speakers=AsyncMock(
            side_effect=ProviderRejectedRequestException("refused", code="x")
        )
    )
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    with pytest.raises(ProviderRejectedRequestException):
        await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=True)  # type: ignore[arg-type]
