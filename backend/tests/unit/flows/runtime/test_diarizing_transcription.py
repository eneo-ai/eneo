from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.diarizing_transcription import DiarizingFlowTranscriber
from eneo.flows.runtime.recording_parts import PartBounds, RecordingAudio
from eneo.flows.runtime.remote_transcription import (
    RemoteFlowTranscriber,
    RemoteTranscriptionResult,
)
from eneo.flows.runtime.speaker_enrichment import DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT
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


def _recording(tmp_path) -> RecordingAudio:
    def spool(name: str) -> SpooledAudio:
        return SpooledAudio(tmp_path / name, "0" * 64, 1, "audio/webm", name)

    return RecordingAudio(
        parts=(spool("a.webm"), spool("b.webm")),
        file_ids=(uuid4(), uuid4()),
        joined=spool("recording.wav"),
        bounds=(PartBounds(0.0, 10.0), PartBounds(10.0, 5.0)),
    )


async def test_a_recording_is_transcribed_per_part_and_labelled_once(tmp_path) -> None:
    recording = _recording(tmp_path)
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(
            side_effect=[
                TranscribedAudio(
                    "hej", 10.0, segments=(TranscriptSegment("hej", 0.0, 10.0),)
                ),
                TranscribedAudio(
                    "då", 5.0, segments=(TranscriptSegment("då", 0.0, 5.0),)
                ),
            ]
        )
    )
    remote = _remote()
    transcriber = DiarizingFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    result = await transcriber.transcribe_recording(
        recording,
        MODEL,
        language="sv",
        observer=None,
        max_speakers=3,  # type: ignore[arg-type]
    )

    assert [
        call.kwargs["filepath"]
        for call in registry.transcribe_from_filepath.await_args_list
    ] == [part.path for part in recording.parts]
    remote.label_speakers.assert_awaited_once()
    labelled = remote.label_speakers.await_args
    assert labelled.args[0] is recording.joined
    assert labelled.kwargs["segments"] == (
        TranscriptSegment("hej", 0.0, 10.0),
        TranscriptSegment("då", 10.0, 15.0),
    )
    assert labelled.kwargs["max_speakers"] == 3
    assert result.diarization == "external"
    assert result.duration_seconds == 15.0


async def test_the_full_service_transcribes_a_recording_in_one_job(tmp_path) -> None:
    recording = _recording(tmp_path)
    remote = RemoteFlowTranscriber.__new__(RemoteFlowTranscriber)
    remote.transcribe = AsyncMock(  # type: ignore[method-assign]
        return_value=TranscribedAudio("x", 15.0, diarization="external")
    )

    result = await remote.transcribe_recording(
        recording,
        MODEL,
        language="sv",
        observer=None,
        max_speakers=None,  # type: ignore[arg-type]
    )

    remote.transcribe.assert_awaited_once()
    call = remote.transcribe.await_args
    assert call.args[0] is recording.joined
    assert call.kwargs["diarize"] is True
    assert call.kwargs["file_id"] == recording.file_ids[0]
    assert result.duration_seconds == 15.0
