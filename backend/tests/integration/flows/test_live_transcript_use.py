import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.api import flow_run_lifecycle_router, flow_run_retry_router
from eneo.flows.application.flow_run_service import FlowRunService
from eneo.flows.flow_input_limits import resolve_flow_input_limits
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.flows.runtime.executor import FlowRunExecutor
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.flows.runtime.live_transcription.tickets import LiveTranscriptionGrant
from eneo.flows.runtime.service_transcription import RegistryFlowTranscriber
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.flows.runtime.transcription import FlowTranscribers
from eneo.main.container.container import Container
from eneo.server.dependencies.container import load_container_upload_admission
from tests.integration.flows.test_flow_live_transcription_session import (
    UNREACHABLE_ENDPOINT,
    _add_to_space,
    _create_space,
    _create_transcription_model,
    _published_flow,
    _remove_from_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _upload_second_of_silence(client, headers, flow) -> UUID:
    payload = BytesIO()
    with wave.open(payload, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)
    uploaded = await client.post(
        f"/api/v1/flows/{flow.flow_id}/steps/{flow.step_id}/runtime-files/",
        headers=headers,
        files={"upload_file": ("live.wav", payload.getvalue(), "audio/wav")},
    )
    assert uploaded.status_code == 201, uploaded.text
    return UUID(uploaded.json()["id"])


@pytest.fixture
async def live_recording(client, flow_process_auth_headers, db_container, monkeypatch):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client, headers, db_container, wizard={"transcription_diarization": False}
    )
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        AsyncMock(),
    )
    file = SimpleNamespace(id=await _upload_second_of_silence(client, headers, flow))
    async with db_container() as container:
        user, tenant = container.user(), container.tenant()
        transcript_id = await LiveTranscriptRepository(container.session()).create(
            LiveTranscriptionGrant(
                tenant_id=user.tenant_id,
                user_id=user.id,
                flow_id=UUID(flow.flow_id),
                flow_version=1,
                step_id=UUID(flow.step_id),
                model_id=UUID(flow.model_id),
                recording_id="recording_123",
                max_seconds=60,
            ),
            text="Live text.",
            segments=[{"text": "Live text.", "start": 0.0, "end": 1.0}],
            received_audio_seconds=1.0,
        )
        row = await LiveTranscriptRepository(container.session()).get(
            transcript_id, tenant_id=user.tenant_id
        )
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    return SimpleNamespace(
        flow=flow,
        headers=headers,
        file=file,
        transcript_id=transcript_id,
        user=user,
        tenant=tenant,
    )


@asynccontextmanager
async def _executed(
    db_container, case, run_id: UUID, registry, *, completion_service=None
) -> AsyncIterator[tuple[object, Container, dict[str, object]]]:
    """Run ``run_id`` in a worker whose batch transcription is ``registry``."""
    user, tenant, flow_id = case.user, case.tenant, case.flow.flow_id
    async with db_container(), sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        worker = Container(
            session=providers.Object(session),
            tenant=providers.Object(tenant),
            user=providers.Object(user),
        )
        admission = await load_container_upload_admission(worker)
        executor = FlowRunExecutor(
            # The worker opens this on a session of its own; here the executor's audit service serves.
            read_audit_service=lambda: nullcontext(executor.audit_service),
            runtime_actor=FlowRunActor.from_user(user=user),
            session=session,
            flow_repo=worker.flow_repo(),
            flow_run_repo=worker.flow_run_repo(),
            flow_run_review_checkpoint_repo=worker.flow_run_review_checkpoint_repo(),
            flow_run_terminalizer=worker.flow_run_terminalizer(),
            flow_version_repo=worker.flow_version_repo(),
            space_repo=worker.tenant_scoped_space_repo(),
            completion_service=completion_service or AsyncMock(),
            file_repo=worker.file_repo(),
            file_content_loader=worker.file_content_loader(),
            file_service=worker.file_service(),
            template_asset_repo=worker.flow_template_asset_repo(),
            encryption_service=worker.encryption_service(),
            audit_service=SimpleNamespace(log_async=AsyncMock(return_value=uuid4())),
            transcribers=FlowTranscribers(
                model=RegistryFlowTranscriber(registry),
                with_speaker_service=AsyncMock(),
            ),
            max_inline_text_bytes=1024 * 1024,
            input_limits=resolve_flow_input_limits(
                tenant.flow_settings, defaults=admission
            ),
        )
        outcome = await executor.execute(
            run_id=run_id,
            flow_id=UUID(flow_id),
            tenant_id=user.tenant_id,
            run_revision=1,
            dispatch_task_id="live-use-test",
            retry_count=0,
        )
        yield session, worker, outcome


async def _admit(container, case):
    await load_container_upload_admission(container)
    return await container.flow_run_service().create_run(
        flow_id=UUID(case.flow.flow_id),
        input_payload_json=None,
        step_inputs={
            UUID(case.flow.step_id): FlowRunStepInputFiles(
                file_ids=(case.file.id,),
                live_transcript_id=case.transcript_id,
                streamed=True,
            )
        },
    )


async def _cleanup(case):
    async with sessionmanager.session() as session, session.begin():
        return await LiveTranscriptRepository(session).delete_expired_unbound(
            tenant_id=case.user.tenant_id,
            now=datetime.now(timezone.utc) + timedelta(days=2),
            limit=10,
            dry_run=False,
            flow_id=UUID(case.flow.flow_id),
        )


async def test_cleanup_skips_binding_in_flight_and_never_deletes_the_bound_row(
    live_recording, db_container
):
    case = live_recording
    async with db_container() as container:
        await _admit(container, case)
        row = await LiveTranscriptRepository(container.session()).get(
            case.transcript_id, tenant_id=case.user.tenant_id
        )
        assert row.bound_file_id == case.file.id
        assert (await _cleanup(case)).purged_count == 0
    assert (await _cleanup(case)).purged_count == 0
    async with db_container() as container:
        row = await LiveTranscriptRepository(container.session()).get(
            case.transcript_id, tenant_id=case.user.tenant_id
        )
        assert row is not None
        assert row.bound_file_id == case.file.id


async def test_cleanup_winning_before_binding_is_recorded_as_not_found(
    live_recording, db_container
):
    case = live_recording
    assert (await _cleanup(case)).purged_count == 1
    async with db_container() as container:
        created = await _admit(container, case)
    facts = created.run.input_payload_json["step_inputs"][case.flow.step_id]
    assert facts["live_transcript_refusal"] == "not_found"


async def test_a_refused_run_leaves_the_transcript_unbound(
    live_recording, db_container, monkeypatch
):
    # Binding and the run are one transaction: a run that is not created binds nothing.
    case = live_recording
    monkeypatch.setattr(
        FlowRunService,
        "_create_persisted_run",
        AsyncMock(side_effect=RuntimeError("refused")),
    )
    with pytest.raises(RuntimeError, match="refused"):
        async with db_container() as container:
            await _admit(container, case)
    async with db_container() as container:
        row = await LiveTranscriptRepository(container.session()).get(
            case.transcript_id, tenant_id=case.user.tenant_id
        )
        assert row.bound_file_id is None
        assert list(row.bound_file_ids) == []


async def test_full_run_uses_live_segments_and_persists_evidence(
    live_recording, client, db_container
):
    case = live_recording
    response = await client.post(
        f"/api/v1/flows/{case.flow.flow_id}/runs/",
        headers={**case.headers, "Idempotency-Key": "live-recording"},
        json={
            "step_inputs": {
                case.flow.step_id: {
                    "file_ids": [str(case.file.id)],
                    "streamed": True,
                    "live_transcript_id": str(case.transcript_id),
                }
            }
        },
    )
    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["id"])
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(side_effect=AssertionError("Unexpected ASR"))
    )
    async with _executed(db_container, case, run_id, registry) as (
        session,
        worker,
        outcome,
    ):
        registry.transcribe_from_filepath.assert_not_awaited()
        assert outcome["status"] == "completed", outcome
        run = await worker.flow_run_repo().get(
            run_id=run_id, tenant_id=case.user.tenant_id
        )
        assert run.output_payload_json["text"] == "Live text."
        results = await worker.flow_run_repo().list_step_results(
            run_id=run_id, tenant_id=case.user.tenant_id
        )
        metadata = results[0].input_payload_json["transcription"]
        assert metadata["transcript_origin"] == "live"
        assert "live_fallback_reason" not in metadata
        assert metadata["source"]["run_id"] == str(run_id)
        source = await FlowTranscriptSourceRepository(session=session).get_for_attempt(
            tenant_id=case.user.tenant_id,
            run_id=run_id,
            step_id=UUID(case.flow.step_id),
            attempt_no=1,
        )
        assert source is not None
        assert source.segments is not None
        assert [(s["text"], s["start"], s["end"]) for s in source.segments] == [
            ("Live text.", 0.0, 1.0)
        ]


@pytest.mark.parametrize("removed_before_the_run", [False, True])
async def test_a_live_models_text_is_the_runs_transcript(
    removed_before_the_run, client, flow_process_auth_headers, db_container, monkeypatch
):
    """The source picks the model: audio streamed through the flow's live model
    is not transcribed again by its transcription model. A live model removed
    between the recording and the run leaves the transcription model to write
    it, and the step says why."""
    headers = dict(flow_process_auth_headers)
    space_id = await _create_space(client, headers)
    live = await _create_transcription_model(
        client, headers, endpoint=UNREACHABLE_ENDPOINT, supports_realtime=True
    )
    await _add_to_space(db_container, space_id, live["id"])
    flow = await _published_flow(
        client,
        headers,
        db_container,
        supports_realtime=False,
        space_id=space_id,
        wizard={
            "transcription_live_model": {"id": live["id"]},
            "transcription_diarization": False,
        },
    )
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        AsyncMock(),
    )
    file_id = await _upload_second_of_silence(client, headers, flow)
    async with db_container() as container:
        user, tenant = container.user(), container.tenant()
        transcript_id = await LiveTranscriptRepository(container.session()).create(
            LiveTranscriptionGrant(
                tenant_id=user.tenant_id,
                user_id=user.id,
                flow_id=UUID(flow.flow_id),
                flow_version=1,
                step_id=UUID(flow.step_id),
                model_id=UUID(live["id"]),
                recording_id="recording_456",
                max_seconds=60,
            ),
            text="Live text.",
            segments=[{"text": "Live text.", "start": 0.0, "end": 1.0}],
            received_audio_seconds=1.0,
        )
    if removed_before_the_run:
        await _remove_from_space(db_container, space_id, live["id"])
    response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        headers={**headers, "Idempotency-Key": "separate-live-model"},
        json={
            "step_inputs": {
                flow.step_id: {
                    "file_ids": [str(file_id)],
                    "streamed": True,
                    "live_transcript_id": str(transcript_id),
                }
            }
        },
    )
    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["id"])
    case = SimpleNamespace(flow=flow, user=user, tenant=tenant)
    registry = SimpleNamespace(
        transcribe_from_filepath=(
            AsyncMock(return_value=TranscribedAudio("Batch text.", 1.0))
            if removed_before_the_run
            else AsyncMock(side_effect=AssertionError("Unexpected ASR"))
        )
    )

    async with _executed(db_container, case, run_id, registry) as (_, worker, outcome):
        assert outcome["status"] == "completed", outcome
        run = await worker.flow_run_repo().get(run_id=run_id, tenant_id=user.tenant_id)
        results = await worker.flow_run_repo().list_step_results(
            run_id=run_id, tenant_id=user.tenant_id
        )
        metadata = results[0].input_payload_json["transcription"]
    steps = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/steps/", headers=headers
    )
    assert steps.status_code == 200, steps.text
    step = steps.json()[0]
    # What the run was sent, for a new run started with the same files.
    assert (
        step["runtime_input_streamed"],
        step["runtime_input_live_transcript_id"],
    ) == (True, str(transcript_id))
    if removed_before_the_run:
        registry.transcribe_from_filepath.assert_awaited_once()
        assert run.output_payload_json["text"] == "Batch text."
        assert metadata["model_id"] == flow.model_id
        assert (
            step["transcript_origin"],
            step["live_fallback_reason"],
            step["transcript_model_name"],
        ) == ("batch", "unavailable", metadata["model"])
    else:
        registry.transcribe_from_filepath.assert_not_awaited()
        assert run.output_payload_json["text"] == "Live text."
        # The live model wrote the text, so it is the transcript's model.
        assert metadata["model_id"] == live["id"] != flow.model_id
        assert metadata["model"] == live["model_name"]
        assert (
            step["transcript_origin"],
            step["live_fallback_reason"],
            step["transcript_model_name"],
        ) == ("live", None, live["model_name"])


@pytest.mark.parametrize("live_model_in_space", [True, False])
async def test_an_uploaded_recording_is_transcribed_by_the_transcription_model(
    live_model_in_space, client, flow_process_auth_headers, db_container, monkeypatch
):
    """The source picks the model: an uploaded recording is transcribed by the
    flow's transcription model, whether or not its live model is there."""
    headers = dict(flow_process_auth_headers)
    space_id = await _create_space(client, headers)
    live = await _create_transcription_model(
        client, headers, endpoint=UNREACHABLE_ENDPOINT, supports_realtime=True
    )
    await _add_to_space(db_container, space_id, live["id"])
    flow = await _published_flow(
        client,
        headers,
        db_container,
        supports_realtime=False,
        space_id=space_id,
        wizard={
            "transcription_live_model": {"id": live["id"]},
            "transcription_diarization": False,
        },
    )
    if not live_model_in_space:
        await _remove_from_space(db_container, space_id, live["id"])
    monkeypatch.setattr(
        flow_run_lifecycle_router,
        "dispatch_flow_run_recoverably_after_commit",
        AsyncMock(),
    )
    file_id = await _upload_second_of_silence(client, headers, flow)
    response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        headers={**headers, "Idempotency-Key": f"batch-{live_model_in_space}"},
        json={"step_inputs": {flow.step_id: {"file_ids": [str(file_id)]}}},
    )
    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["id"])
    async with db_container() as container:
        case = SimpleNamespace(
            flow=flow, user=container.user(), tenant=container.tenant()
        )
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(
            return_value=TranscribedAudio("Batch text.", 1.0)
        )
    )

    async with _executed(db_container, case, run_id, registry) as (_, worker, outcome):
        assert outcome["status"] == "completed", outcome
        registry.transcribe_from_filepath.assert_awaited_once()
        model = registry.transcribe_from_filepath.await_args.kwargs[
            "transcription_model"
        ]
        assert str(model.id) == flow.model_id != live["id"]
        run = await worker.flow_run_repo().get(
            run_id=run_id, tenant_id=case.user.tenant_id
        )
        assert run.output_payload_json["text"] == "Batch text."
        results = await worker.flow_run_repo().list_step_results(
            run_id=run_id, tenant_id=case.user.tenant_id
        )
        metadata = results[0].input_payload_json["transcription"]
        assert metadata["transcript_origin"] == "batch"


async def test_a_streamed_recording_in_parts_keeps_its_live_text_in_each_part(
    live_recording, client, db_container
):
    """A recording streamed in two parts is written by the live text alone,
    each passage in the part that holds it, and binds every part in order."""
    case = live_recording
    second = await _upload_second_of_silence(client, case.headers, case.flow)
    parts = [case.file.id, second]
    async with db_container() as container:
        transcript_id = await LiveTranscriptRepository(container.session()).create(
            LiveTranscriptionGrant(
                tenant_id=case.user.tenant_id,
                user_id=case.user.id,
                flow_id=UUID(case.flow.flow_id),
                flow_version=1,
                step_id=UUID(case.flow.step_id),
                model_id=UUID(case.flow.model_id),
                recording_id="recording_parts",
                max_seconds=60,
            ),
            text="Första. Andra.",
            segments=[
                {"text": "Första.", "start": 0.1, "end": 0.9},
                {"text": " Andra.", "start": 1.1, "end": 1.9},
            ],
            received_audio_seconds=2.0,
            part_start_samples=[16000],
        )
        row = await LiveTranscriptRepository(container.session()).get(
            transcript_id, tenant_id=case.user.tenant_id
        )
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=1)

    def submit(file_ids, key):
        return client.post(
            f"/api/v1/flows/{case.flow.flow_id}/runs/",
            headers={**case.headers, "Idempotency-Key": key},
            json={
                "step_inputs": {
                    case.flow.step_id: {
                        "file_ids": [str(file_id) for file_id in file_ids],
                        "single_recording": True,
                        "streamed": True,
                        "live_transcript_id": str(transcript_id),
                    }
                }
            },
        )

    async def refusal(response):
        assert response.status_code == 201, response.text
        async with db_container() as container:
            run = await container.flow_run_repo().get(
                run_id=UUID(response.json()["id"]), tenant_id=case.user.tenant_id
            )
        return run.input_payload_json["step_inputs"][case.flow.step_id].get(
            "live_transcript_refusal"
        )

    # Admission records why it could not bind; the run is still created.
    assert await refusal(await submit(parts[:1], "parts-one")) == "files_mismatch"
    response = await submit(parts, "parts-all")
    assert await refusal(response) is None
    # Bound to these parts in this order; no other order may claim the text.
    assert await refusal(await submit(parts[::-1], "parts-reordered")) == (
        "already_bound"
    )
    async with db_container() as container:
        row = await LiveTranscriptRepository(container.session()).get(
            transcript_id, tenant_id=case.user.tenant_id
        )
        assert (row.bound_file_id, list(row.bound_file_ids)) == (parts[0], parts)
        assert list(row.part_start_samples) == [16000]

    run_id = UUID(response.json()["id"])
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(side_effect=AssertionError("Unexpected ASR"))
    )
    async with _executed(db_container, case, run_id, registry) as (
        session,
        _,
        outcome,
    ):
        registry.transcribe_from_filepath.assert_not_awaited()
        assert outcome["status"] == "completed", outcome
        source = await FlowTranscriptSourceRepository(session=session).get_for_attempt(
            tenant_id=case.user.tenant_id,
            run_id=run_id,
            step_id=UUID(case.flow.step_id),
            attempt_no=1,
        )
        assert [
            (s["file_index"], s["text"], round(s["start"], 3)) for s in source.segments
        ] == [(0, "Första.", 0.1), (1, "Andra.", 0.1)]


async def test_the_run_graph_says_why_while_the_transcription_model_works(
    live_recording, client, db_container
):
    """The graph a run page polls carries why the live text is not used as soon
    as the step's attempt decides it, while the step still runs and the run's
    revision stays the same, and keeps saying it once the step is done."""
    case = live_recording
    response = await client.post(
        f"/api/v1/flows/{case.flow.flow_id}/runs/",
        headers={**case.headers, "Idempotency-Key": "streamed-graph"},
        json={
            "step_inputs": {
                case.flow.step_id: {"file_ids": [str(case.file.id)], "streamed": True}
            }
        },
    )
    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["id"])
    graph_url = f"/api/v1/flows/{case.flow.flow_id}/graph/?run_id={run_id}"
    status_url = f"/api/v1/flows/{case.flow.flow_id}/runs/{run_id}/status/"
    seen: dict[str, object] = {}

    async def transcribe(*_args: object, **_kwargs: object) -> TranscribedAudio:
        graph = await client.get(graph_url, headers=case.headers)
        status = await client.get(status_url, headers=case.headers)
        seen["graph"], seen["status"] = graph.json(), status.json()
        return TranscribedAudio("Batch text.", 1.0)

    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(side_effect=transcribe)
    )
    async with _executed(db_container, case, run_id, registry) as (_, _, outcome):
        assert outcome["status"] == "completed", outcome

    (node,) = [n for n in seen["graph"]["nodes"] if n["id"] == case.flow.step_id]
    assert (node["run_status"], node["live_fallback_reason"]) == (
        "running",
        "not_received",
    )
    assert seen["status"]["status"] == "running"
    after = await client.get(graph_url, headers=case.headers)
    (node,) = [n for n in after.json()["nodes"] if n["id"] == case.flow.step_id]
    assert (node["run_status"], node["live_fallback_reason"]) == (
        "completed",
        "not_received",
    )


@pytest.mark.parametrize("usable", [True, False])
async def test_a_run_started_again_from_a_retry_keeps_its_streamed_audio(
    usable, client, flow_process_auth_headers, db_container, monkeypatch
):
    """A retry reuses the completed streamed step of a run whose next step
    failed. Its steps say how that audio was submitted, so a run started again
    from them uses the live text without the transcription model, or says why
    it cannot. An unusable transcript is one the run named but could not bind."""
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        wizard={"transcription_diarization": False},
        summarize=True,
    )
    for router in (flow_run_lifecycle_router, flow_run_retry_router):
        monkeypatch.setattr(
            router, "dispatch_flow_run_recoverably_after_commit", AsyncMock()
        )
    file_id = await _upload_second_of_silence(client, headers, flow)
    async with db_container() as container:
        user, tenant = container.user(), container.tenant()
        live_id = await LiveTranscriptRepository(container.session()).create(
            LiveTranscriptionGrant(
                tenant_id=user.tenant_id,
                user_id=user.id,
                flow_id=UUID(flow.flow_id),
                flow_version=1,
                step_id=UUID(flow.step_id),
                model_id=UUID(flow.model_id),
                recording_id="recording_retry",
                max_seconds=60,
            ),
            text="Live text.",
            segments=[{"text": "Live text.", "start": 0.0, "end": 1.0}],
            received_audio_seconds=1.0,
        )
    if not usable:
        live_id = uuid4()
    case = SimpleNamespace(flow=flow, user=user, tenant=tenant)
    base = f"/api/v1/flows/{flow.flow_id}"

    async def run(step_input: dict[str, object], key: str) -> list[dict]:
        created = await client.post(
            f"{base}/runs/",
            headers={**headers, "Idempotency-Key": key},
            json={"step_inputs": {flow.step_id: step_input}},
        )
        assert created.status_code == 201, created.text
        run_id = UUID(created.json()["id"])
        batch = AsyncMock(return_value=TranscribedAudio("Batch text.", 1.0))
        async with _executed(
            db_container,
            case,
            run_id,
            SimpleNamespace(transcribe_from_filepath=batch),
            completion_service=AsyncMock(
                get_response=AsyncMock(side_effect=RuntimeError("model down"))
            ),
        ) as (_, _, outcome):
            assert outcome["status"] == "failed", outcome
        assert batch.await_count == (0 if usable else 1)
        steps = await client.get(f"{base}/runs/{run_id}/steps/", headers=headers)
        assert steps.status_code == 200, steps.text
        assert [step["status"] for step in steps.json()] == ["completed", "failed"]
        transcribed = steps.json()[0]
        assert (
            transcribed["transcript_origin"],
            transcribed["live_fallback_reason"],
        ) == (("live", None) if usable else ("batch", "not_found"))
        return [run_id, transcribed]

    source_id, _ = await run(
        {
            "file_ids": [str(file_id)],
            "streamed": True,
            "live_transcript_id": str(live_id),
        },
        f"source-{usable}",
    )
    retried = await client.post(
        f"{base}/runs/{source_id}/retry/",
        headers={**headers, "Idempotency-Key": f"retry-{usable}"},
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["reused_step_orders"] == [1]
    child_id = retried.json()["run"]["id"]
    child_steps = await client.get(f"{base}/runs/{child_id}/steps/", headers=headers)
    assert child_steps.status_code == 200, child_steps.text
    reused = child_steps.json()[0]
    assert (
        reused["runtime_input_streamed"],
        reused["runtime_input_live_transcript_id"],
    ) == (True, str(live_id))
    graph = await client.get(f"{base}/graph/?run_id={child_id}", headers=headers)
    (node,) = [n for n in graph.json()["nodes"] if n["id"] == flow.step_id]
    assert node["live_fallback_reason"] == (None if usable else "not_found")

    # A run started again from the retry's steps, as a client does it.
    await run(
        {
            "file_ids": reused["runtime_input_file_ids"],
            "streamed": reused["runtime_input_streamed"],
            "live_transcript_id": reused["runtime_input_live_transcript_id"],
        },
        f"again-{usable}",
    )


async def test_a_failed_attempt_keeps_why_the_live_text_was_not_used(
    live_recording, client, db_container
):
    """The decision is stored before the transcription model is called, so a step
    that then fails still says why and which model was to write the text."""
    case = live_recording
    response = await client.post(
        f"/api/v1/flows/{case.flow.flow_id}/runs/",
        headers={**case.headers, "Idempotency-Key": "streamed-no-id"},
        json={
            "step_inputs": {
                case.flow.step_id: {"file_ids": [str(case.file.id)], "streamed": True}
            }
        },
    )
    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["id"])
    registry = SimpleNamespace(
        transcribe_from_filepath=AsyncMock(side_effect=RuntimeError("model down"))
    )
    async with _executed(db_container, case, run_id, registry) as (_, _, outcome):
        registry.transcribe_from_filepath.assert_awaited_once()
        assert outcome["status"] == "failed", outcome
    steps = await client.get(
        f"/api/v1/flows/{case.flow.flow_id}/runs/{run_id}/steps/",
        headers=case.headers,
    )
    assert steps.status_code == 200, steps.text
    step = steps.json()[0]
    assert step["status"] == "failed"
    assert step["transcript_origin"] is None
    assert step["live_fallback_reason"] == "not_received"
    model = registry.transcribe_from_filepath.await_args.kwargs["transcription_model"]
    assert step["transcript_model_name"] == model.name
