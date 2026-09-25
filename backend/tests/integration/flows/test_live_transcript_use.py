import wave
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.flows.api import flow_run_lifecycle_router
from eneo.flows.flow_input_limits import resolve_flow_input_limits
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.flows.runtime.diarizing_transcription import RegistryFlowTranscriber
from eneo.flows.runtime.executor import FlowRunExecutor
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.flows.runtime.live_transcription.tickets import LiveTranscriptionGrant
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.server.dependencies.container import load_container_upload_admission
from tests.integration.flows.test_flow_live_transcription_session import _published_flow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
    file = SimpleNamespace(id=UUID(uploaded.json()["id"]))
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


async def _admit(container, case):
    await load_container_upload_admission(container)
    return await container.flow_run_service().create_run(
        flow_id=UUID(case.flow.flow_id),
        input_payload_json=None,
        step_inputs={
            UUID(case.flow.step_id): SimpleNamespace(
                file_ids=(case.file.id,),
                live_transcript_id=case.transcript_id,
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


async def test_cleanup_winning_before_binding_refuses_admission(
    live_recording, db_container
):
    case = live_recording
    assert (await _cleanup(case)).purged_count == 1
    with pytest.raises(NotFoundException) as error:
        async with db_container() as container:
            await _admit(container, case)
    assert error.value.code == "flow_run_live_transcript_not_found"


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
    async with db_container(), sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        worker = Container(
            session=providers.Object(session),
            tenant=providers.Object(case.tenant),
            user=providers.Object(case.user),
        )
        admission = await load_container_upload_admission(worker)
        executor = FlowRunExecutor(
            runtime_actor=FlowRunActor.from_user(user=case.user),
            session=session,
            flow_repo=worker.flow_repo(),
            flow_run_repo=worker.flow_run_repo(),
            flow_run_review_checkpoint_repo=worker.flow_run_review_checkpoint_repo(),
            flow_run_terminalizer=worker.flow_run_terminalizer(),
            flow_version_repo=worker.flow_version_repo(),
            space_repo=worker.tenant_scoped_space_repo(),
            completion_service=AsyncMock(),
            file_repo=worker.file_repo(),
            file_content_loader=worker.file_content_loader(),
            file_service=worker.file_service(),
            template_asset_repo=worker.flow_template_asset_repo(),
            encryption_service=worker.encryption_service(),
            audit_service=SimpleNamespace(log_async=AsyncMock(return_value=uuid4())),
            transcriber=RegistryFlowTranscriber(registry),
            max_inline_text_bytes=1024 * 1024,
            input_limits=resolve_flow_input_limits(
                case.tenant.flow_settings, defaults=admission
            ),
        )
        outcome = await executor.execute(
            run_id=run_id,
            flow_id=UUID(case.flow.flow_id),
            tenant_id=case.user.tenant_id,
            run_revision=1,
            dispatch_task_id="live-use-test",
            retry_count=0,
        )
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
