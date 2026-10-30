from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.files.transcript import TranscriptSegment, TranscriptWord
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.recording_parts import PartBounds, RecordingAudio
from eneo.flows.runtime.run_cancellation import (
    FlowStepCancelledError,
    run_cancel_probe_scope,
)
from eneo.flows.runtime.service_enrichment import (
    DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT,
    SpeakerServiceFailed,
    WordTimingOutcome,
    _timing_failure,
)
from eneo.flows.runtime.service_transcription import ServiceFlowTranscriber
from eneo.flows.runtime.step_deadline import StepDeadline, step_deadline_scope
from eneo.main.exceptions import (
    OpenAIException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    EmptyTranscriptionInterval,
)
from eneo.transcription_services.client import TranscriptionJobResult
from tests.unit.flows.runtime.test_remote_transcription import make_transcriber
from tests.unit.transcription_services.scripted_service import (
    JOB_ID,
    RESULT_BODY,
    TIMED_BODY,
    ScriptedService,
    accepted,
    status,
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
            return_value=TranscriptionJobResult(
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
    transcriber = ServiceFlowTranscriber(registry, remote)  # type: ignore[arg-type]

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
    transcriber = ServiceFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=True)  # type: ignore[arg-type]

    assert remote.label_speakers.await_args.kwargs["words"] is None
    assert remote.label_speakers.await_args.kwargs["segments"] == SEGMENTS


# The transcript the model wrote for TIMED_BODY, as one five-minute window.
SPOKEN = "Hej och välkomna."
TIMED_LINES = (
    TranscriptSegment(
        "Hej och",
        0.0,
        2.0,
        words=(
            TranscriptWord("Hej", 0.0, 0.4, 0.98),
            TranscriptWord("och", 0.5, 0.8, 0.91),
        ),
    ),
    TranscriptSegment(
        "välkomna.", 2.4, 5.2, words=(TranscriptWord("välkomna.", 2.4, 3.1, 0.0),)
    ),
)


def _timing_service(
    *,
    status_answer: httpx.Response | None = None,
    result: dict[str, object] = TIMED_BODY,
) -> ScriptedService:
    return ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status_answer or status("completed")],
        result_responses=[httpx.Response(200, json=result)],
    )


async def _time(
    spool_contract, service: ScriptedService, observer=None
) -> TranscribedAudio:
    """The model writes SPOKEN; the service is asked to time it, not to label."""
    spool_contract.duration_seconds = 5.2
    spool = await spool_contract.spool(FILE)
    registry = _registry(
        TranscribedAudio(SPOKEN, 5.2, segments=(TranscriptSegment(SPOKEN, 0.0, 5.2),))
    )
    transcriber = ServiceFlowTranscriber(registry, make_transcriber(service))  # type: ignore[arg-type]
    return await transcriber.transcribe(  # type: ignore[arg-type]
        spool, MODEL, file_id=FILE.id, language="sv", diarize=False, observer=observer
    )


async def test_without_labels_the_service_times_the_models_words(
    spool_contract,
) -> None:
    service = _timing_service()

    result = await _time(spool_contract, service)

    # The text stays the model's own; the timed lines are its structured view.
    assert result.text == SPOKEN
    assert result.segments == (TranscriptSegment(SPOKEN, 0.0, 5.2),)
    assert result.transcript_segments == TIMED_LINES
    assert (result.alignment, result.word_timing) == ("forced", "done")
    assert (result.diarization, result.diarization_elapsed_ms) == (None, None)
    assert result.speaker_review is None
    assert b'name="task"\r\n\r\ntimestamp\r\n' in service.requests[0].read()


async def test_a_token_without_letters_the_aligner_drops_still_times_the_words(
    spool_contract,
) -> None:
    # The service's aligner hears words, not a lone dash; its lines leave it out.
    spool_contract.duration_seconds = 5.2
    spoken = "Hej – och välkomna."
    transcriber = ServiceFlowTranscriber(
        _registry(
            TranscribedAudio(
                spoken, 5.2, segments=(TranscriptSegment(spoken, 0.0, 5.2),)
            )
        ),
        make_transcriber(_timing_service()),
    )  # type: ignore[arg-type]

    result = await transcriber.transcribe(  # type: ignore[arg-type]
        await spool_contract.spool(FILE), MODEL, file_id=FILE.id, diarize=False
    )

    assert (result.text, result.word_timing) == (spoken, "done")
    assert result.transcript_segments == TIMED_LINES


def _with_first_words(words: list[dict[str, object]]) -> dict[str, object]:
    """TIMED_BODY with the first line's words replaced; its text stays."""
    lines = [dict(line) for line in TIMED_BODY["segments"]]  # type: ignore[union-attr]
    lines[0]["words"] = words
    return {**TIMED_BODY, "segments": lines}


def _with_lines(**changes: object) -> dict[str, object]:
    """TIMED_BODY with every line changed; the text still renders the lines."""
    lines = [{**line, **changes} for line in TIMED_BODY["segments"]]  # type: ignore[union-attr]
    speaker = f"{changes['speaker']}: " if changes.get("speaker") else ""
    return {
        **TIMED_BODY,
        "segments": lines,
        "text": "\n".join(
            f"[00:00:0{int(line['start'])} - 00:00:0{int(line['end'])}] "
            f"{speaker}{line['text']}"
            for line in lines
        ),
    }


@pytest.mark.parametrize(
    ("service", "reason"),
    [
        (ScriptedService(submit_responses=[httpx.Response(401)]), "credentials"),
        (
            ScriptedService(
                submit_responses=[
                    httpx.Response(
                        422,
                        json={
                            "detail": [
                                {
                                    "loc": ["body", "task"],
                                    "msg": "Input should be 'transcribe', "
                                    "'diarize' or 'align'",
                                }
                            ]
                        },
                    )
                ]
            ),
            "unsupported",
        ),
        # A service that predates tasks transcribes with its own model.
        (_timing_service(result=RESULT_BODY), "unsupported"),
        (
            ScriptedService(submit_responses=[httpx.ConnectError("dummy-secret")]),
            "unavailable",
        ),
        (
            _timing_service(
                status_answer=httpx.Response(
                    200,
                    json={
                        "job_id": JOB_ID,
                        "status": "failed",
                        "failure_kind": "internal",
                        "error": "aligner failed",
                    },
                )
            ),
            "failed",
        ),
        (_timing_service(status_answer=status("cancelled")), "failed"),
        (_timing_service(result=_with_lines(words=[])), "no_timings"),
        # Timings that do not time the line word by word are no timings: one word
        # of two, a word the line does not say, or a word that ends before it starts.
        (
            _timing_service(
                result=_with_first_words(
                    [{"word": "Hej", "start": 0.0, "end": 0.4, "probability": 0.9}]
                )
            ),
            "no_timings",
        ),
        (
            _timing_service(
                result=_with_first_words(
                    [
                        {"word": "Hej", "start": 0.0, "end": 0.4, "probability": 0.9},
                        {"word": "Annat", "start": 0.5, "end": 0.8, "probability": 0.9},
                    ]
                )
            ),
            "no_timings",
        ),
        (
            _timing_service(
                result=_with_first_words(
                    [
                        {"word": "Hej", "start": 0.0, "end": 0.4, "probability": 0.9},
                        {"word": "och", "start": 9.0, "end": 0.5, "probability": 0.9},
                    ]
                )
            ),
            "no_timings",
        ),
        (
            _timing_service(
                result=_with_first_words(
                    [{"word": "Hej och", "start": 0.0, "end": 0.8, "probability": 0.9}]
                )
            ),
            "no_timings",
        ),
        (_timing_service(result=_with_lines(speaker="SPEAKER_00")), "no_timings"),
        (
            _timing_service(result=_with_lines(text="Adjö.")),
            "no_timings",
        ),
        # Lines that do not render the service's own text are no lines.
        (_timing_service(result={**TIMED_BODY, "text": SPOKEN}), "no_timings"),
    ],
    ids=[
        "credentials-rejected",
        "task-refused",
        "task-ignored",
        "unreachable",
        "job-failed",
        "job-cancelled",
        "lines-without-words",
        "a-line-partly-timed",
        "a-word-the-line-does-not-say",
        "a-word-ending-before-it-starts",
        "one-entry-for-the-whole-line",
        "lines-with-speakers",
        "other-words",
        "lines-not-the-text",
    ],
)
async def test_a_timing_failure_keeps_the_models_text_and_says_why(
    spool_contract, service: ScriptedService, reason: str
) -> None:
    result = await _time(spool_contract, service)

    assert (result.text, result.transcript_segments, result.alignment) == (
        SPOKEN,
        None,
        None,
    )
    assert result.word_timing == reason


class _GapObserver:
    operation_scope = "tenant/run/step/attempt-1"

    async def started(self, request: object) -> object:
        raise ProviderCallObserverError("receipt not written")


@pytest.mark.parametrize("ending", ["cancelled", "deadline", "evidence_gap"])
async def test_cancellation_the_deadline_and_an_evidence_gap_still_end_the_step(
    spool_contract, ending: str
) -> None:
    service = _timing_service()
    expected, observer = {
        "cancelled": (FlowStepCancelledError, None),
        "deadline": (TypedIOValidationException, None),
        "evidence_gap": (ProviderCallObserverError, _GapObserver()),
    }[ending]

    with (
        run_cancel_probe_scope(
            AsyncMock(return_value=True) if ending == "cancelled" else None
        ),
        step_deadline_scope(
            StepDeadline.start(0 if ending == "deadline" else 60), step_order=1
        ),
        pytest.raises(expected),
    ):
        await _time(spool_contract, service, observer=observer)

    assert service.submit_count == 0


async def test_an_empty_transcript_is_not_timed(spool_contract) -> None:
    spool = await spool_contract.spool(FILE)
    remote = SimpleNamespace(time_words=AsyncMock())
    transcriber = ServiceFlowTranscriber(
        _registry(TranscribedAudio("", 30.0, segments=())),
        remote,  # type: ignore[arg-type]
    )

    result = await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=False)  # type: ignore[arg-type]

    assert (result.text, result.word_timing) == ("", None)
    remote.time_words.assert_not_awaited()


async def test_empty_transcript_skips_labelling_instead_of_failing(
    spool_contract,
) -> None:
    spool_contract.duration_seconds = 30.0
    spool = await spool_contract.spool(FILE)
    registry = _registry(TranscribedAudio("", 30.0, segments=()))
    remote = _remote()
    transcriber = ServiceFlowTranscriber(registry, remote)  # type: ignore[arg-type]

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
    transcriber = ServiceFlowTranscriber(registry, remote)  # type: ignore[arg-type]

    # The speaker service's own failure, with its cause, never the model's.
    with pytest.raises(SpeakerServiceFailed) as failed:
        await transcriber.transcribe(spool, MODEL, file_id=FILE.id, diarize=True)  # type: ignore[arg-type]
    assert isinstance(failed.value.__cause__, ProviderRejectedRequestException)


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
    transcriber = ServiceFlowTranscriber(registry, remote)  # type: ignore[arg-type]

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


def test_a_typed_timing_failure_that_says_timed_out_is_not_an_outage() -> None:
    # Kills the mutant that classifies by message text.
    error = OpenAIException("Word timing timed out.", code="skill_prompt_ownership")

    assert _timing_failure(error) is WordTimingOutcome.FAILED
