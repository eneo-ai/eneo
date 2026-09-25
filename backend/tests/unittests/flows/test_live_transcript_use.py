from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.database.tables.flow_tables import FlowLiveTranscripts
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.flow_run_error import TranscriptionFailureKind
from eneo.flows.runtime.diarizing_transcription import DiarizingFlowTranscriber
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.flows.runtime.remote_transcription import RemoteTranscriptionResult
from eneo.flows.runtime.transcription import (
    TranscriptionFailure,
    TranscriptionProviderRejectedError,
)
from eneo.flows.runtime.transcription_runtime import (
    AudioRuntimeDeps,
    AudioRuntimeRequest,
    resolve_transcribe_and_attach_audio_input,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
)
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import (
    _audio_file,
    _patch_run_input_payload,
    _run,
    _runtime_step,
    _SpaceStub,
)

spool_contract = audio_spool_test_support.spool_contract


@pytest.fixture
def live_audio(user, monkeypatch, spool_contract):
    file = _audio_file(name="live.wav")
    step = _runtime_step()
    model = SimpleNamespace(id=uuid4(), name="Whisper", model_name="whisper-1")
    transcript_id = uuid4()
    run = _run(
        user=user,
        payload={
            "step_inputs": {
                str(step.step_id): {"live_transcript_id": str(transcript_id)}
            },
            "speaker_labels": False,
            "max_speakers": 3,
        },
    )
    row = FlowLiveTranscripts(
        id=transcript_id,
        tenant_id=run.tenant_id,
        user_id=run.principal_user_id,
        flow_id=run.flow_id,
        flow_version=run.flow_version,
        step_id=step.step_id,
        model_id=model.id,
        recording_id="recording_123",
        bound_file_id=file.id,
        text="Live text.",
        segments=[{"text": "Live text.", "start": 0.0, "end": 42.0}],
        received_audio_seconds=42.0,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    lookup = AsyncMock(return_value=row)
    monkeypatch.setattr(LiveTranscriptRepository, "get", lookup)
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(
            return_value=TranscribedAudio(
                "Batch text.", 42.0, segments=(TranscriptSegment("Batch text.", 0, 42),)
            )
        )
    )
    remote = SimpleNamespace(
        label_speakers=AsyncMock(
            return_value=RemoteTranscriptionResult(
                text="Live text.",
                duration_seconds=42.0,
                model="whisper-1",
                language="sv",
                alignment="forced",
                segments=(
                    TranscriptSegment("Live text.", 0, 42, speaker="SPEAKER_00"),
                ),
            )
        )
    )
    space_repo = AsyncMock()
    space_repo.get_space_by_assistant.return_value = _SpaceStub([model], model)
    run_repo = AsyncMock()
    _patch_run_input_payload(run_repo, run)
    staged = []
    request = AudioRuntimeRequest(
        run=run,
        step=step,
        context={"flow_input": {}},
        version_metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(model.id)},
                "transcription_language": "sv",
            }
        },
        files=[file],
        requested_ids=[file.id],
        max_audio_files=5,
        max_inline_text_bytes=100_000,
    )
    deps = AudioRuntimeDeps(
        transcriber=DiarizingFlowTranscriber(registry, remote),
        space_repo=space_repo,
        flow_run_repo=run_repo,
        audit_service=None,
        actor=FlowRunActor.from_user(user=user),
        open_audio_download=spool_contract.downloads([file]),
        apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
        commit=AsyncMock(),
        stage_transcript_source=lambda reference, source: staged.append(
            (reference, source)
        ),
    )
    return SimpleNamespace(
        row=row,
        lookup=lookup,
        registry=registry,
        remote=remote,
        request=request,
        deps=deps,
        staged=staged,
    )


async def test_live_segments_skip_asr_and_preserve_source(live_audio, spool_contract):
    case = live_audio
    result = await resolve_transcribe_and_attach_audio_input(
        request=case.request, deps=case.deps
    )
    case.registry.transcribe_from_filepath.assert_not_awaited()
    case.remote.label_speakers.assert_not_awaited()
    assert result.text == "Live text."
    assert result.transcription_metadata["transcript_origin"] == "live"
    assert "live_fallback_reason" not in result.transcription_metadata
    reference, prepared = case.staged[0]
    assert result.transcription_metadata["source"] == reference.model_dump(mode="json")
    assert prepared.source.segments == [
        {
            "file_index": 0,
            "start": 0.0,
            "end": 42.0,
            "speaker": None,
            "text": "Live text.",
        }
    ]
    assert sum(spool_contract.duration_calls.values()) == 1


@pytest.mark.parametrize("alignment", ["forced", "segment_split", "segment_only"])
async def test_live_speaker_enrichment_uses_live_segments_and_run_bound(
    live_audio, alignment
):
    from dataclasses import replace

    case = live_audio
    case.request.run.input_payload_json["speaker_labels"] = True
    case.remote.label_speakers.return_value = replace(
        case.remote.label_speakers.return_value, alignment=alignment
    )
    result = await resolve_transcribe_and_attach_audio_input(
        request=case.request, deps=case.deps
    )
    case.registry.transcribe_from_filepath.assert_not_awaited()
    case.remote.label_speakers.assert_awaited_once()
    assert case.remote.label_speakers.await_args.kwargs["segments"] == (
        TranscriptSegment("Live text.", 0, 42),
    )
    assert case.remote.label_speakers.await_args.kwargs["max_speakers"] == 3
    assert result.transcription_metadata["transcript_origin"] == "live"
    assert result.transcription_metadata["alignment"] == alignment
    assert (result.diarization_reduced_precision_message is not None) == (
        alignment != "forced"
    )


@pytest.mark.parametrize(
    "condition,reason,labels",
    [
        ("duration", "duration_mismatch", False),
        ("no_segments", "no_timing", False),
        ("no_segments", "no_timing", True),
        ("missing", "unavailable", False),
        ("expired", "unavailable", False),
        ("different_file", "unavailable", False),
    ],
)
async def test_unusable_live_transcript_calls_batch_once(
    live_audio, condition, reason, labels
):
    case = live_audio
    case.request.run.input_payload_json["speaker_labels"] = labels
    if condition == "duration":
        case.row.received_audio_seconds = 45
    elif condition == "no_segments":
        case.row.segments = None
    elif condition == "missing":
        case.lookup.return_value = None
    elif condition == "expired":
        case.row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    else:
        case.row.bound_file_id = uuid4()
    result = await resolve_transcribe_and_attach_audio_input(
        request=case.request, deps=case.deps
    )
    case.registry.transcribe_from_filepath.assert_awaited_once()
    assert result.transcription_metadata["transcript_origin"] == "batch"
    assert result.transcription_metadata["live_fallback_reason"] == reason
    if labels:
        case.remote.label_speakers.assert_awaited_once()
        assert (
            case.remote.label_speakers.await_args.kwargs["segments"][0].text
            == "Batch text."
        )
    else:
        assert result.text == "Batch text."
        case.remote.label_speakers.assert_not_awaited()


async def test_live_enrichment_failure_keeps_batch_error_mapping_without_asr(
    live_audio,
):
    case = live_audio
    case.request.run.input_payload_json["speaker_labels"] = True
    case.remote.label_speakers.side_effect = TranscriptionProviderRejectedError(
        "refused",
        failure_kind=TranscriptionFailureKind.INPUT,
        service_reason="invalid_audio",
    )
    with pytest.raises(TranscriptionFailure) as error:
        await resolve_transcribe_and_attach_audio_input(
            request=case.request, deps=case.deps
        )
    case.registry.transcribe_from_filepath.assert_not_awaited()
    case.remote.label_speakers.assert_awaited_once()
    assert (
        error.value.run_error_details.transcription_failure_kind
        is TranscriptionFailureKind.INPUT
    )
    assert error.value.run_error_details.transcription_service_reason == "invalid_audio"
