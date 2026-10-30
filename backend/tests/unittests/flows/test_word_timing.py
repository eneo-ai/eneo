"""A flow's transcription service times the words of a transcript whose
speakers are not labelled. The text never depends on it: a timing that fails
leaves the model's text without segments and says why in the step's
transcription metadata."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.files.transcript import TranscriptSegment
from eneo.flows.domain.transcript_source import TranscriptSourceOmissionReason
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.service_transcription import (
    RegistryFlowTranscriber,
    ServiceFlowTranscriber,
)
from eneo.flows.runtime.transcription import (
    FlowTranscribers,
    TranscriptSourcePreparation,
)
from eneo.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    AudioRuntimeResolution,
    resolve_transcribe_and_attach_audio_input,
)
from eneo.main.exceptions import NotFoundException
from tests.unit.flows.runtime.test_remote_transcription import make_transcriber
from tests.unit.transcription_services.scripted_service import (
    TIMED_BODY,
    ScriptedService,
    accepted,
    status,
)
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import (
    _SPEAKER_CHOICE,
    _SPEAKER_SERVICE,
    _SWITCHED_OFF_SERVICE,
    _audio_file,
    _patch_run_input_payload,
    _run,
    _runtime_step,
    _SpaceStub,
)

spool_contract = audio_spool_test_support.spool_contract

MODEL = SimpleNamespace(
    id=uuid4(), name="Whisper", model_name="whisper-1", can_access=True
)
# What the model writes for TIMED_BODY's audio, as one chunk window.
SPOKEN = "Hej och välkomna."
# The wizard key left out: the author made no choice.
NO_CHOICE = object()


def _registry(*texts: str) -> SimpleNamespace:
    """The flow's model: one transcript per file, in one chunk window each."""
    return SimpleNamespace(
        transcribe_from_filepath=AsyncMock(
            side_effect=[
                TranscribedAudio(
                    text, 5.2, segments=(TranscriptSegment(text, 0.0, 5.2),)
                )
                for text in texts
            ]
        )
    )


def _service(*results: dict[str, object] | httpx.Response) -> ScriptedService:
    """One completed timestamp job per result; a response is a refused submit."""
    return ScriptedService(
        submit_responses=[
            result if isinstance(result, httpx.Response) else accepted()
            for result in results
        ],
        status_responses=[
            status("completed")
            for result in results
            if not isinstance(result, httpx.Response)
        ],
        result_responses=[
            httpx.Response(200, json=result)
            for result in results
            if not isinstance(result, httpx.Response)
        ],
    )


async def _resolve(
    user,
    spool_contract,
    *,
    registry: SimpleNamespace,
    service: ScriptedService | None = None,
    pick: object = _SPEAKER_CHOICE,
    payload: dict[str, Any] | None = None,
    space: _SpaceStub | None = None,
    files_count: int = 1,
    single_recording: bool = False,
    with_service: AsyncMock | None = None,
) -> tuple[AudioRuntimeResolution, TranscriptSourcePreparation, AsyncMock]:
    files = [_audio_file(name=f"part-{index}.wav") for index in range(files_count)]
    space_repo = AsyncMock()
    space_repo.one.return_value = space or _SpaceStub([MODEL], MODEL)
    step = _runtime_step()
    run = _run(
        user=user,
        payload={
            **(payload or {}),
            **(
                {"step_inputs": {str(step.step_id): {"single_recording": True}}}
                if single_recording
                else {}
            ),
        },
    )
    run_repo = AsyncMock()
    _patch_run_input_payload(run_repo, run)
    staged: list[TranscriptSourcePreparation] = []
    if with_service is None:
        with_service = AsyncMock(
            return_value=ServiceFlowTranscriber(
                registry,  # type: ignore[arg-type]
                make_transcriber(service or _service()),
            )
        )
    resolved = await resolve_transcribe_and_attach_audio_input(
        request=AudioRuntimeRequest(
            run=run,
            step=step,
            context={"flow_input": {}},
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(MODEL.id)},
                    "transcription_language": "sv",
                    "transcription_diarization": False,
                    **(
                        {}
                        if pick is NO_CHOICE
                        else {"transcription_speaker_service": pick}
                    ),
                }
            },
            files=files,
            requested_ids=[file.id for file in files],
            max_audio_files=5,
            max_inline_text_bytes=100_000,
        ),
        deps=AudioRuntimeDeps(
            transcribers=FlowTranscribers(
                model=RegistryFlowTranscriber(registry),  # type: ignore[arg-type]
                with_speaker_service=with_service,
            ),
            flow_repo=AsyncMock(),
            space_repo=space_repo,
            flow_run_repo=run_repo,
            audit_service=None,
            actor=FlowRunActor.from_user(user=user),
            open_audio_download=spool_contract.downloads(files),
            apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
            commit=AsyncMock(),
            stage_transcript_source=lambda reference, source: staged.append(source),
            stage_run_transcript=lambda reference, transcript: None,
        ),
    )
    return resolved, staged[0], with_service


def _form(service: ScriptedService, index: int = 0) -> bytes:
    return [request for request in service.requests if request.method == "POST"][
        index
    ].read()


async def test_without_speaker_labels_the_chosen_service_times_the_words(
    user, spool_contract
) -> None:
    service = _service(TIMED_BODY)

    resolved, prepared, with_service = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN),
        service=service,
        # A bound the run settled is a speaker bound; a timing job sends none.
        payload={"speaker_labels": False, "max_speakers": 3},
    )

    with_service.assert_awaited_once_with(_SPEAKER_SERVICE)
    # Downstream steps read the model's text, as they do without a service.
    assert resolved.text == SPOKEN
    metadata = resolved.transcription_metadata
    assert metadata["word_timing"] == {"status": "done"}
    assert (metadata["diarization"], metadata["alignment"]) == (None, "forced")
    assert (metadata["speakers"], metadata["max_speakers"]) == ([], None)
    # The run identified no speakers, and its evidence names no speaker service.
    assert (metadata["speaker_service"], metadata["speaker_service_id"]) == (
        None,
        None,
    )
    assert resolved.diarization_reduced_precision_message is None
    assert prepared.source.segments == [
        {
            "file_index": 0,
            "start": 0.0,
            "end": 2.0,
            "speaker": None,
            "text": "Hej och",
        },
        {
            "file_index": 0,
            "start": 2.4,
            "end": 5.2,
            "speaker": None,
            "text": "välkomna.",
        },
    ]
    assert prepared.source.speaker_review is None
    assert prepared.source_hash is not None
    assert prepared.alignment == "forced"
    assert prepared.words == [
        {
            "segment_index": 0,
            "words": [
                {"word": "Hej", "start": 0.0, "end": 0.4, "probability": 0.98},
                {"word": "och", "start": 0.5, "end": 0.8, "probability": 0.91},
            ],
        },
        {
            "segment_index": 1,
            "words": [
                {"word": "välkomna.", "start": 2.4, "end": 3.1, "probability": 0.0}
            ],
        },
    ]
    form = _form(service)
    assert b'name="task"\r\n\r\ntimestamp\r\n' in form
    assert b'name="max_speakers"' not in form


def _untimed(
    resolved: AudioRuntimeResolution, prepared: TranscriptSourcePreparation
) -> str:
    """The reason of a step that kept the model's text without segments."""
    assert resolved.text == SPOKEN
    assert prepared.source.segments is None
    assert prepared.bounds.segments_omitted_reason is (
        TranscriptSourceOmissionReason.NO_SEGMENTS
    )
    assert prepared.words is None
    word_timing = resolved.transcription_metadata["word_timing"]
    assert word_timing["status"] == "failed"
    return word_timing["reason"]


async def test_a_service_that_refuses_the_task_leaves_the_text_untimed(
    user, spool_contract
) -> None:
    # An older service answers 422 to a task it does not know.
    service = _service(httpx.Response(422, json={"detail": "unknown task"}))

    resolved, prepared, _ = await _resolve(
        user, spool_contract, registry=_registry(SPOKEN), service=service
    )

    assert _untimed(resolved, prepared) == "unsupported"


@pytest.mark.parametrize(
    "space",
    [
        _SpaceStub([MODEL], MODEL, speaker_services=[]),
        _SpaceStub([MODEL], MODEL, speaker_services=[_SWITCHED_OFF_SERVICE]),
    ],
    ids=["no_longer_granted", "switched_off"],
)
async def test_a_chosen_service_the_space_cannot_use_leaves_the_text_untimed(
    user, spool_contract, space: _SpaceStub
) -> None:
    registry = _registry(SPOKEN)

    resolved, prepared, with_service = await _resolve(
        user,
        spool_contract,
        registry=registry,
        space=space,
        pick={"id": str(_SWITCHED_OFF_SERVICE.id)},
    )

    # Nothing stands in for the chosen service, and the step is not refused.
    with_service.assert_not_awaited()
    registry.transcribe_from_filepath.assert_awaited_once()
    assert _untimed(resolved, prepared) == "unavailable"


async def test_a_service_removed_before_its_key_is_read_leaves_the_text_untimed(
    user, spool_contract
) -> None:
    resolved, prepared, with_service = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN),
        with_service=AsyncMock(side_effect=NotFoundException("gone")),
    )

    with_service.assert_awaited_once_with(_SPEAKER_SERVICE)
    assert _untimed(resolved, prepared) == "unavailable"


@pytest.mark.parametrize("pick", [NO_CHOICE, None], ids=["no_choice", "chose_none"])
async def test_without_a_chosen_service_nothing_is_timed_or_asked(
    user, spool_contract, pick: object
) -> None:
    resolved, prepared, with_service = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN),
        pick=pick,
        with_service=AsyncMock(side_effect=AssertionError("no service is asked")),
    )

    with_service.assert_not_awaited()
    assert resolved.text == SPOKEN
    assert "word_timing" not in resolved.transcription_metadata
    assert prepared.bounds.segments_omitted_reason is (
        TranscriptSourceOmissionReason.NO_SEGMENTS
    )


async def test_the_files_of_a_step_are_timed_all_or_none(user, spool_contract) -> None:
    other = "Tack för i dag."
    other_timed = {
        **TIMED_BODY,
        "text": f"[00:00:00 - 00:00:05] {other}",
        "segments": [
            {
                "start": 0.0,
                "end": 5.2,
                "speaker": None,
                "text": other,
                "words": [
                    {"word": word, "start": 0.0, "end": 1.0} for word in other.split()
                ],
            }
        ],
    }
    timed, _, _ = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN, other),
        service=_service(TIMED_BODY, other_timed),
        files_count=2,
    )
    refused, prepared, _ = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN, other),
        service=_service(TIMED_BODY, httpx.Response(422, json={"detail": "x"})),
        files_count=2,
    )

    assert timed.transcription_metadata["word_timing"] == {"status": "done"}
    # One untimed file leaves the whole step without segments: a reader seeks
    # by segments only when every file has them.
    assert refused.text == timed.text == f"{SPOKEN}\n\n{other}"
    assert prepared.source.segments is None
    assert prepared.words is None
    assert refused.transcription_metadata["word_timing"] == {
        "status": "failed",
        "reason": "unsupported",
    }


async def test_the_parts_of_one_recording_are_timed_part_by_part(
    user, spool_contract
) -> None:
    other = "Tack för i dag."
    service = _service(
        TIMED_BODY,
        {
            **TIMED_BODY,
            "text": f"[00:00:00 - 00:00:05] {other}",
            "segments": [
                {
                    "start": 0.0,
                    "end": 5.2,
                    "text": other,
                    "words": [
                        {"word": word, "start": index, "end": index + 1.0}
                        for index, word in enumerate(other.split())
                    ],
                }
            ],
        },
    )

    resolved, prepared, _ = await _resolve(
        user,
        spool_contract,
        registry=_registry(SPOKEN, other),
        service=service,
        files_count=2,
        single_recording=True,
    )

    # Without labels nothing is joined: each part is its own timestamp job.
    assert service.submit_count == 2
    assert resolved.transcription_metadata["word_timing"] == {"status": "done"}
    assert {segment["file_index"] for segment in prepared.source.segments or []} == {
        0,
        1,
    }
