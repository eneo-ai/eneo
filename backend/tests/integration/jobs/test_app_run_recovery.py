import asyncio
import wave
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from arq.jobs import Job as ArqJob
from arq.jobs import JobStatus

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.apps.app_runs.api import app_run_worker
from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppService
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.job_table import Jobs
from eneo.files.transcriber import Transcriber
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.job_repo import JobRepository
from eneo.main.models import Channel, ChannelType, RedisMessage, Status
from eneo.worker import task_manager

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def recovery_recording(
    client,
    admin_user_api_key,
    db_container,
    completion_model_factory,
    transcription_model_factory,
):
    async with db_container() as container:
        session = container.session()
        await completion_model_factory(session, "recovery-model", is_default=True)
        await transcription_model_factory(session, "recovery-whisper", is_default=True)
    headers = {"X-API-Key": admin_user_api_key.key}
    space = await client.post(
        "/api/v1/spaces/", json={"name": "Recovery"}, headers=headers
    )
    assert space.status_code == 201, space.text
    app = await client.post(
        f"/api/v1/spaces/{space.json()['id']}/applications/apps/",
        json={"name": "Meeting transcription"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_url = f"/api/v1/apps/{app.json()['id']}/"
    configured = await client.patch(
        app_url, json={"input_fields": [{"type": "audio-upload"}]}, headers=headers
    )
    assert configured.status_code == 200, configured.text
    recording = BytesIO()
    with wave.open(recording, "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(1600))
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("meeting.wav", recording.getvalue(), "audio/wav")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    return app_url, upload.json()["id"], recording.getvalue()


@pytest.mark.parametrize("terminal", [Status.COMPLETE, Status.FAILED])
async def test_audio_run_reaches_worker_after_commit_and_publishes_saved_result(
    terminal,
    client,
    admin_user_api_key,
    recovery_recording,
    redis_client,
    monkeypatch,
):
    headers = {"X-API-Key": admin_user_api_key.key}
    app_url, file_id, recording = recovery_recording

    async def complete(self, *, model, transcription_inputs, **kwargs):
        assert transcription_inputs == ["meeting transcript"]
        if terminal == Status.FAILED:
            raise RuntimeError("Summary provider unavailable")
        return CompletionModelResponse(
            completion=Completion(text="meeting summary"),
            model=model,
            total_token_count=5,
        )

    monkeypatch.setattr(
        Transcriber,
        "transcribe_from_filepath",
        AsyncMock(return_value="meeting transcript"),
    )
    monkeypatch.setattr(CompletionService, "get_response", complete)

    # Pause the real request just after queue_app_run so a worker could observe
    # any delivery made before the API transaction commits.
    queued = asyncio.get_running_loop().create_future()
    release = asyncio.Event()
    original = AppRunService.queue_app_run

    async def pause_after_create(self, *args, **kwargs):
        run = await original(self, *args, **kwargs)
        queued.set_result(run)
        await release.wait()
        return run

    monkeypatch.setattr(AppRunService, "queue_app_run", pause_after_create)
    request = asyncio.create_task(
        client.post(
            f"{app_url}runs/",
            json={"files": [{"id": file_id}]},
            headers=headers,
        )
    )
    try:
        run = await asyncio.wait_for(queued, timeout=5)
        assert (
            await job_manager.get_job_status(run.job_id, Task.RUN_APP)
            == JobStatus.not_found
        )
    finally:
        release.set()
        response = await asyncio.wait_for(request, timeout=5)
    assert response.status_code == 203, response.text
    pending = await client.get(f"/api/v1/app-runs/{run.id}/", headers=headers)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == Status.QUEUED
    assert pending.json()["input"]["files"][0]["transcription"] is None

    assert job_manager._redis is not None
    delivery = ArqJob(str(run.job_id), redis=job_manager._redis)
    async with asyncio.timeout(5):
        while (info := await delivery.info()) is None:
            await asyncio.sleep(0.01)
    assert info.function == Task.RUN_APP.value
    [params] = info.args
    assert isinstance(params, AppRunParams)
    channel = Channel(type=ChannelType.APP_RUN_UPDATES, user_id=run.user_id)

    release_terminal_publish = asyncio.Event()
    publish = task_manager.publish_task_status

    async def publish_and_wait(channel, message):
        await publish(channel, message)
        if message.status == terminal:
            await release_terminal_publish.wait()

    monkeypatch.setattr(task_manager, "publish_task_status", publish_and_wait)
    async with redis_client.pubsub() as subscription:
        await subscription.subscribe(channel.channel_string)
        await subscription.get_message(timeout=2)
        running = asyncio.create_task(
            app_run_worker.run_app({"job_id": delivery.job_id}, params)
        )
        try:
            async with asyncio.timeout(5):
                while True:
                    event = await subscription.get_message(timeout=1)
                    if event is not None:
                        update = RedisMessage.model_validate_json(event["data"])
                        if update.id == run.id and update.status == terminal:
                            break
            result = await client.get(f"/api/v1/app-runs/{run.id}/", headers=headers)
            assert result.status_code == 200, result.text
            assert result.json()["status"] == terminal
            expected_output = "meeting summary" if terminal == Status.COMPLETE else None
            assert result.json()["output"] == expected_output
            assert (
                result.json()["input"]["files"][0]["transcription"]
                == "meeting transcript"
            )
            file_id = result.json()["input"]["files"][0]["id"]
            audio = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
            assert audio.status_code == 200, audio.text
            assert audio.json()["transcription"] == "meeting transcript"
            signed = await client.post(
                f"/api/v1/files/{file_id}/signed-url/",
                json={"content_disposition": "attachment"},
                headers=headers,
            )
            assert signed.status_code == 200, signed.text
            downloaded = await client.get(signed.json()["url"])
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.headers["content-disposition"].startswith("attachment")
            assert downloaded.content == recording
        finally:
            release_terminal_publish.set()
            succeeded = await asyncio.wait_for(running, timeout=5)
        assert succeeded is (terminal == Status.COMPLETE)


@pytest.mark.parametrize("claimed", [False, True])
async def test_app_dispatch_error_fails_only_an_unclaimed_run(
    claimed,
    db_session,
    client,
    admin_user_api_key,
    recovery_recording,
    monkeypatch,
):
    headers = {"X-API-Key": admin_user_api_key.key}
    app_url, file_id, _ = recovery_recording
    enqueue = job_manager.enqueue
    delivery = asyncio.get_running_loop().create_future()
    async with db_session() as worker:

        async def lose_acknowledgement(task, job_id, params):
            if task != Task.RUN_APP:
                return await enqueue(task, job_id, params)
            if claimed:
                assert await JobRepository(worker).mark_job_started(job_id)
            delivery.set_result((job_id, params, asyncio.current_task()))
            raise ConnectionError("queue unavailable")

        monkeypatch.setattr(job_manager, "enqueue", lose_acknowledgement)
        response = await client.post(
            f"{app_url}runs/", json={"files": [{"id": file_id}]}, headers=headers
        )
        assert response.status_code == 203, response.text
        job_id, params, callback = await asyncio.wait_for(delivery, 5)
        await asyncio.wait_for(asyncio.shield(callback), 5)

    detail = await client.get(f"/api/v1/app-runs/{params.id}/", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == (Status.IN_PROGRESS if claimed else Status.FAILED)
    async with db_session() as session:
        job = await session.get(Jobs, job_id)
        assert job is not None
        if claimed:
            assert job.failure_code is None
        else:
            assert job.failure_code == JobFailureCode.DISPATCH_FAILED
            assert job.finished_at is not None
            assert not await JobRepository(session).mark_job_started(job_id)


@pytest.fixture
async def app_run_fixture(
    db_session, admin_user, app_factory, completion_model_factory
):
    async with db_session() as session:
        model = await completion_model_factory(session, "gpt-4")
        app = await app_factory(session, "Meeting transcription", model.id)
        app_id, model_id, space_id = app.id, model.id, app.space_id

    async def create(*, status=Status.QUEUED, age=timedelta(), task=Task.RUN_APP):
        run_id, job_id = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        async with db_session() as session:
            session.add(
                Jobs(
                    id=job_id,
                    user_id=admin_user.id,
                    task=task.value,
                    status=status.value,
                    updated_at=now - age,
                    failure_code=JobFailureCode.PROCESSING_INTERRUPTED.value
                    if status == Status.FAILED
                    else None,
                )
            )
            await session.flush()
            session.add(
                AppRuns(
                    id=run_id,
                    job_id=job_id,
                    app_id=app_id,
                    completion_model_id=model_id,
                    tenant_id=admin_user.tenant_id,
                    user_id=admin_user.id,
                )
            )
        return (
            job_id,
            AppRunParams(id=run_id, user_id=admin_user.id, file_ids=[], app_id=app_id),
            space_id,
        )

    return create


async def test_late_delivery_cannot_restart_a_failed_app_run(
    app_run_fixture, db_session, monkeypatch
):
    job_id, params, _ = await app_run_fixture(status=Status.FAILED)
    load_app = AsyncMock(side_effect=AssertionError("A failed run reached the app"))
    monkeypatch.setattr(AppService, "get_app", load_app)

    assert await app_run_worker.run_app({"job_id": str(job_id)}, params) is False

    load_app.assert_not_awaited()
    async with db_session() as session:
        job = await session.get(Jobs, job_id)
        assert job is not None
        assert job.status == Status.FAILED.value
        assert job.failure_code == JobFailureCode.PROCESSING_INTERRUPTED.value


async def test_reaper_fails_orphaned_runs_and_notifies_the_open_result(
    app_run_fixture, db_session, redis_client, client, admin_user_api_key, monkeypatch
):
    old = timedelta(hours=3)
    orphan, params, space_id = await app_run_fixture(age=old)
    active, _, _ = await app_run_fixture(age=old)
    fresh, _, _ = await app_run_fixture()
    other_task, _, _ = await app_run_fixture(age=old, task=Task.TRANSCRIPTION)
    channel = Channel(type=ChannelType.APP_RUN_UPDATES, user_id=params.user_id)
    release_publish = asyncio.Event()
    publish = app_run_worker.publish_task_status

    async def publish_and_wait(channel, message):
        await publish(channel, message)
        await release_publish.wait()

    monkeypatch.setattr(app_run_worker, "publish_task_status", publish_and_wait)

    # Invoke the registered maintenance entry point with its actual session wrapper.
    cron = next(
        task
        for task in app_run_worker.worker.cron_jobs
        if task.name == "cron:fail_expired_app_runs"
    )
    async with redis_client.pubsub() as subscription:
        await subscription.subscribe(channel.channel_string)
        await subscription.get_message(timeout=2)  # Acknowledge subscription.
        async with db_session() as running:
            assert await JobRepository(running).mark_job_started(active)
            reaping = asyncio.create_task(cron.coroutine({}))
            try:
                event = await subscription.get_message(timeout=5)
                assert event is not None
                update = RedisMessage.model_validate_json(event["data"])
                assert update.id == params.id
                assert update.status == Status.FAILED
                assert update.additional_data == {
                    "app_id": str(params.app_id),
                    "space": {"id": str(space_id), "personal": False},
                }

                # A subscriber can refetch as soon as Redis delivers the event.
                result = await client.get(
                    f"/api/v1/app-runs/{params.id}/",
                    headers={"X-API-Key": admin_user_api_key.key},
                )
                assert result.status_code == 200, result.text
                assert result.json()["status"] == Status.FAILED
            finally:
                release_publish.set()
                await asyncio.wait_for(reaping, timeout=5)

    async with db_session() as session:
        orphaned_run = await session.get(AppRuns, params.id)
        assert orphaned_run.job_id == orphan
        job = await session.get(Jobs, orphan)
        assert job.status == Status.FAILED.value
        assert job.failure_code == JobFailureCode.PROCESSING_INTERRUPTED.value
        assert job.finished_at is not None
        assert (await session.get(Jobs, active)).status == Status.IN_PROGRESS.value
        assert (await session.get(Jobs, fresh)).status == Status.QUEUED.value
        assert (await session.get(Jobs, other_task)).status == Status.QUEUED.value
