"""Transcribe steps keep their segments; corrections anchor to them.

The transcription model is faked at the transcriber boundary (the adapter
is never built); the speaker service is faked at its client; the flow
services, the executor and the corrections service are real.
"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from eneo.database.tables.spaces_table import SpacesTranscriptionModels
from eneo.files.file_models import FileContentVariant
from eneo.files.transcriber import Transcriber
from eneo.files.transcript import TranscriptSegment
from eneo.flows.definition import (
    FlowDefinition,
    FormField,
    LlmStep,
    SpeakerMapping,
    TranscribeStep,
)
from eneo.flows.flow_models import FlowRunStatus, StepResultStatus
from eneo.flows.speaker_service import SpeakerService
from eneo.flows.step_runners import STEP_SPEAKER_SERVICE_UNAVAILABLE
from eneo.flows.transcript_corrections import segments_content_hash
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.server.dependencies.container import load_container_upload_admission
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    AdapterTranscription,
)
from tests.integration.flows.conftest import topic_field

WAV_HEADER = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00" + b"\x00" * 16
)


@pytest.fixture
def transcription(monkeypatch):
    """A transcription model that answers with two chunk windows per file."""

    async def _prepare(self, model):
        return SimpleNamespace(model=model)

    async def _transcribe(self, data, *, adapter, language=None):
        return AdapterTranscription(
            text="### 0:00 - 5:00\n\nVi börjar mötet.\n\n### 5:00 - 7:30\n\nTack alla.",
            segments=(
                TranscriptSegment(text="Vi börjar mötet.", start=0.0, end=300.0),
                TranscriptSegment(text="Tack alla.", start=300.0, end=450.0),
            ),
        )

    monkeypatch.setattr(Transcriber, "prepare_transcription", _prepare)
    monkeypatch.setattr(Transcriber, "transcribe_prepared_bytes", _transcribe)


@pytest.fixture
def speaker_service(monkeypatch):
    """A configured speaker service that labels the two windows with two people."""
    settings = get_settings()
    monkeypatch.setattr(settings, "flow_speaker_service_url", "https://speakers.test")
    calls: list[dict] = []

    async def _label(
        self, data, *, filename, mimetype, segments, model_name, language, max_speakers
    ):
        calls.append(
            {"filename": filename, "segments": len(segments), "max": max_speakers}
        )
        return [
            TranscriptSegment(
                text="Vi börjar mötet.", start=0.0, end=300.0, speaker="SPEAKER_00"
            ),
            TranscriptSegment(
                text="Tack alla.", start=300.0, end=450.0, speaker="SPEAKER_01"
            ),
        ]

    monkeypatch.setattr(SpeakerService, "label_speakers", _label)
    return calls


async def _space_with_audio(
    db_container,
    member_space,
    completion_model_factory,
    name,
    *,
    transcription_model_factory,
):
    """A space with a completion and a transcription model, and a committed
    audio upload (the content store reads through its own session, so the
    upload has to be committed before a run can read it)."""
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, f"{name}-model")
        space = await member_space(session, f"{name} Space", [model.id])
        whisper = await transcription_model_factory(
            session, f"{name}-whisper", is_default=True
        )
        session.add(
            SpacesTranscriptionModels(
                space_id=space.id, transcription_model_id=whisper.id
            )
        )
        await session.flush()
        await load_container_upload_admission(container)
        audio = await container.file_service().save_file(
            UploadFile(
                file=BytesIO(WAV_HEADER),
                filename="mote.wav",
                headers={"content-type": "audio/wav"},
            )
        )
        ids = SimpleNamespace(model_id=model.id, space_id=space.id, audio_id=audio.id)
    return ids


def _definition(model_id, *, speakers: bool, mapping: bool = False) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[
            FormField(key="recording", label="Inspelning", type="audio"),
            FormField(
                key="participants", label="Deltagare", type="text", required=False
            ),
            topic_field(),
        ],
        steps=[
            TranscribeStep(
                key="transcript",
                name="Transkribera",
                source="recording",
                language="sv",
                speaker_labels=speakers,
                speaker_mapping=(
                    SpeakerMapping(participants_field="participants", infer_names=False)
                    if mapping
                    else None
                ),
            ),
            LlmStep(
                key="summary", name="Sammanfatta", prompt="summarize", model_id=model_id
            ),
        ],
    )


async def test_transcribe_step_keeps_segments_and_feeds_the_next_step(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    transcription,
    mock_transcription_models,
    transcription_model_factory,
):
    ids = await _space_with_audio(
        db_container,
        member_space,
        completion_model_factory,
        "transcribe",
        transcription_model_factory=transcription_model_factory,
    )
    async with db_container() as container:
        flow = await publish_flow(
            container,
            SimpleNamespace(id=ids.space_id),
            _definition(ids.model_id, speakers=False),
        )
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "x"}, files={"recording": [ids.audio_id]}
        )
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.COMPLETED, finished.error
        step = finished.steps[0]
        assert step.status == StepResultStatus.COMPLETED
        transcription_meta = step.input_payload_json["transcription"]
        assert transcription_meta["language"] == "sv"
        assert transcription_meta["speaker_labels"] is False
        assert [s["text"] for s in transcription_meta["segments"]] == [
            "Vi börjar mötet.",
            "Tack alla.",
        ]
        assert transcription_meta["segments"][1]["start"] == 300.0
        assert step.output_payload_json["text"].startswith("### 0:00 - 5:00")
        # The next step read the transcript as {{previous}}.
        assert provider.calls[-1]["text_input"] == step.output_payload_json["text"]
        # The transcript is kept on the audio file too (as a content reference;
        # its bytes are readable once this transaction commits).
        references = await container.file_service().repo.get_content_references(
            [ids.audio_id]
        )
        assert FileContentVariant.TRANSCRIPTION in {r.variant for r in references}


async def test_speaker_labels_need_the_service(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    transcription,
    mock_transcription_models,
    transcription_model_factory,
):
    ids = await _space_with_audio(
        db_container,
        member_space,
        completion_model_factory,
        "speakers",
        transcription_model_factory=transcription_model_factory,
    )
    async with db_container() as container:
        # Without a configured service the flow cannot be published.
        with pytest.raises(BadRequestException, match="speaker service"):
            await publish_flow(
                container,
                SimpleNamespace(id=ids.space_id),
                _definition(ids.model_id, speakers=True),
            )


async def test_speaker_labels_and_names_and_corrections(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    transcription,
    speaker_service,
    mock_transcription_models,
    transcription_model_factory,
):
    provider.answer = lambda prompt, text_input: (
        '{"speakers": [{"label": "SPEAKER_00", "name": "Anna", "confidence": "high"},'
        ' {"label": "SPEAKER_01", "name": null, "confidence": "low"}]}'
        if "speaker" in prompt.lower()
        else "LLM"
    )
    ids = await _space_with_audio(
        db_container,
        member_space,
        completion_model_factory,
        "named",
        transcription_model_factory=transcription_model_factory,
    )
    async with db_container() as container:
        flow = await publish_flow(
            container,
            SimpleNamespace(id=ids.space_id),
            _definition(ids.model_id, speakers=True, mapping=True),
        )
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id,
            values={"topic": "x", "participants": "Anna, Erik"},
            files={"recording": [ids.audio_id]},
        )
        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.COMPLETED, finished.error
        assert speaker_service == [{"filename": "mote.wav", "segments": 2, "max": None}]
        step = finished.steps[0]
        meta = step.input_payload_json["transcription"]
        assert [s["speaker"] for s in meta["segments"]] == ["SPEAKER_00", "SPEAKER_01"]
        assert meta["speaker_names"] == {"SPEAKER_00": "Anna", "SPEAKER_01": None}
        assert step.output_payload_json["text"].split("\n") == [
            "[00:00:00 - 00:05:00] Anna: Vi börjar mötet.",
            "[00:05:00 - 00:07:30] SPEAKER_01: Tack alla.",
        ]

        corrections = container.flow_transcript_corrections_service()
        segments = meta["segments"]
        segments_hash = segments_content_hash(segments)
        assert await corrections.list_for_run(run.id, flow_id=flow.id) == []

        saved = await corrections.save(
            run.id,
            step.step_id,
            flow_id=flow.id,
            schema_version=3,
            segments_hash=segments_hash,
            expected_revision=None,
            occurrences=[
                {
                    "segment_index": 1,
                    "char_start": 0,
                    "char_end": 4,
                    "original": "Tack",
                    "corrected": "Tack så mycket",
                }
            ],
            speaker_edits=[
                {
                    "segment_index": 1,
                    "original_speaker": "SPEAKER_01",
                    "speaker": "SPEAKER_00",
                }
            ],
            speaker_names={"SPEAKER_00": "Anna Berg"},
        )
        assert saved.revision == 1 and saved.stale is False
        transcript = await corrections.get_transcript(
            run.id, step.step_id, flow_id=flow.id
        )
        assert transcript.text.split("\n") == [
            "[00:00:00 - 00:05:00] Anna Berg: Vi börjar mötet.",
            "[00:05:00 - 00:07:30] Anna Berg: Tack så mycket alla.",
        ]
        assert transcript.corrections_revision == 1

        # A stale revision or hash is refused with the contract's codes.
        common = dict(
            flow_id=flow.id, schema_version=3, speaker_edits=[], speaker_names=None
        )
        with pytest.raises(BadRequestException) as exc:
            await corrections.save(
                run.id,
                step.step_id,
                segments_hash=segments_hash,
                expected_revision=None,
                occurrences=[],
                **common,
            )
        assert exc.value.code == "flow_transcript_corrections_stale_revision"
        with pytest.raises(BadRequestException) as exc:
            await corrections.save(
                run.id,
                step.step_id,
                segments_hash="0" * 64,
                expected_revision=1,
                occurrences=[],
                **common,
            )
        assert exc.value.code == "flow_transcript_corrections_stale_revision"
        with pytest.raises(BadRequestException) as exc:
            await corrections.save(
                run.id,
                step.step_id,
                segments_hash=segments_hash,
                expected_revision=1,
                occurrences=[
                    {
                        "segment_index": 0,
                        "char_start": 0,
                        "char_end": 2,
                        "original": "XX",
                        "corrected": "",
                    }
                ],
                **common,
            )
        assert exc.value.code == "flow_transcript_corrections_invalid_occurrence"
        assert exc.value.context["reason"] == "original_mismatch"
        replaced = await corrections.save(
            run.id,
            step.step_id,
            segments_hash=segments_hash,
            expected_revision=1,
            occurrences=[],
            **common,
        )
        assert replaced.revision == 2
        listed = await corrections.list_for_run(run.id, flow_id=flow.id)
        assert [c.revision for c in listed] == [2]


async def test_a_run_fails_cleanly_when_the_speaker_service_disappears(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    transcription,
    speaker_service,
    mock_transcription_models,
    monkeypatch,
    transcription_model_factory,
):
    ids = await _space_with_audio(
        db_container,
        member_space,
        completion_model_factory,
        "lost",
        transcription_model_factory=transcription_model_factory,
    )
    async with db_container() as container:
        flow = await publish_flow(
            container,
            SimpleNamespace(id=ids.space_id),
            _definition(ids.model_id, speakers=True),
        )
        monkeypatch.setattr(get_settings(), "flow_speaker_service_url", None)
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "x"}, files={"recording": [ids.audio_id]}
        )
        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.FAILED
        assert finished.error.code == STEP_SPEAKER_SERVICE_UNAVAILABLE
