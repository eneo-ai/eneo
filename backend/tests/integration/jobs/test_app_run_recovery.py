import asyncio
import wave
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from arq.jobs import Job as ArqJob
from arq.jobs import JobStatus

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.apps.app_runs.api import app_run_worker
from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.apps.app_runs.app_run_dispatch import claim_app_job, reconcile_app_runs
from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppService
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.job_table import Jobs
from eneo.files.transcriber import Transcriber
from eneo.jobs.job_manager import DURABLE_APP_FUNCTION, job_manager
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.job_repo import JobRepository
from eneo.main.models import Channel, ChannelType, RedisMessage, Status
from eneo.worker import task_manager

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _run_app_maintenance():
    cron = next(
        task
        for task in app_run_worker.worker.cron_jobs
        if task.name == "cron:reconcile_app_run_jobs"
    )
    await cron.coroutine({})


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


@pytest.mark.parametrize(
    ("terminal", "drop_reply"),
    [(Status.COMPLETE, False), (Status.FAILED, False), (Status.COMPLETE, True)],
)
async def test_audio_run_reaches_worker_after_commit_and_publishes_saved_result(
    terminal,
    drop_reply,
    client,
    admin_user_api_key,
    recovery_recording,
    db_session,
    redis_client,
    monkeypatch,
):
    headers = {"X-API-Key": admin_user_api_key.key}
    app_url, file_id, recording = recovery_recording

    summary_started = asyncio.Event()
    finish_summary = asyncio.Event()

    async def complete(self, *, model, transcription_inputs, **kwargs):
        summary_started.set()
        await finish_summary.wait()
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

    if drop_reply:
        enqueue = job_manager.enqueue
        lost_reply = asyncio.get_running_loop().create_future()

        async def enqueue_without_reply(task, job_id, params):
            delivery = await enqueue(task, job_id, params)
            if task == Task.RUN_APP:
                lost_reply.set_result(asyncio.current_task())
                raise ConnectionError("lost enqueue acknowledgement")
            return delivery

        monkeypatch.setattr(job_manager, "enqueue", enqueue_without_reply)

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
    if drop_reply:
        callback = await asyncio.wait_for(lost_reply, 5)
        await asyncio.wait_for(asyncio.shield(callback), 5)
    pending = await client.get(f"/api/v1/app-runs/{run.id}/", headers=headers)
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == Status.QUEUED
    assert pending.json()["input"]["files"][0]["transcription"] is None

    assert job_manager._redis is not None
    delivery = ArqJob(str(run.job_id), redis=job_manager._redis)
    async with asyncio.timeout(5):
        while (info := await delivery.info()) is None:
            await asyncio.sleep(0.01)
    assert info.function == DURABLE_APP_FUNCTION
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
                await summary_started.wait()
                audio = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
                assert audio.status_code == 200, audio.text
                assert audio.json()["transcription"] == "meeting transcript"
                detail = await client.get(
                    f"/api/v1/app-runs/{run.id}/", headers=headers
                )
                assert (
                    detail.json()["input"]["files"][0]["transcription"]
                    == "meeting transcript"
                )
                async with db_session() as observer:
                    job = await observer.get(Jobs, run.job_id)
                    assert job is not None and job.status == Status.IN_PROGRESS.value
                    # Make the live run eligible by age while its provider is busy.
                    failed = await JobRepository(observer).mark_stale_jobs_failed(
                        tasks=[Task.RUN_APP.value],
                        stale_before=datetime.now(timezone.utc) + timedelta(minutes=1),
                    )
                    assert run.job_id not in failed
            finish_summary.set()
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
            finish_summary.set()
            release_terminal_publish.set()
            succeeded = await asyncio.wait_for(running, timeout=5)
        assert succeeded is (terminal == Status.COMPLETE)


@pytest.mark.parametrize(
    "retained_result", [False, True], ids=["missing-delivery", "old-worker-result"]
)
async def test_committed_run_recovers_without_its_api_callback(
    db_session,
    client,
    admin_user_api_key,
    recovery_recording,
    monkeypatch,
    retained_result,
):
    app_url, file_id, _ = recovery_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    with monkeypatch.context() as stopped_api:
        stopped_api.setattr(
            "eneo.jobs.job_service.after_outer_transaction",
            lambda *args, **kwargs: None,
        )
        response = await client.post(
            f"{app_url}runs/", json={"files": [{"id": file_id}]}, headers=headers
        )
    assert response.status_code == 203, response.text
    run_id = UUID(response.json()["id"])
    async with db_session() as db:
        run = await db.get(AppRuns, run_id)
        assert run is not None
        job = await db.get(Jobs, run.job_id)
        assert job is not None
        assert job.dispatch_envelope == {"version": 1, "file_ids": [file_id]}
        job_id = job.id
        job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    assert await job_manager.get_job_status(job_id, Task.RUN_APP) == JobStatus.not_found
    if retained_result:
        from arq.constants import result_key_prefix

        assert job_manager._redis is not None
        # ARQ refuses to enqueue this ID while an older worker's result exists.
        await job_manager._redis.set(
            result_key_prefix + str(job_id), b"old result", ex=3600
        )
    await asyncio.gather(_run_app_maintenance(), _run_app_maintenance())
    assert await job_manager.get_job_status(job_id, Task.RUN_APP) == JobStatus.queued
    assert job_manager._redis is not None
    delivery = ArqJob(str(job_id), redis=job_manager._redis)
    info = await delivery.info()
    assert info is not None
    [params] = info.args
    assert params.id == run_id and list(map(str, params.file_ids)) == [file_id]


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


@pytest.fixture
async def queued_recording(client, db_session, admin_user_api_key, recovery_recording):
    app_url, file_id, _ = recovery_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    response = await client.post(
        f"{app_url}runs/", json={"files": [{"id": file_id}]}, headers=headers
    )
    assert response.status_code == 203, response.text
    run_id = UUID(response.json()["id"])
    async with db_session() as db:
        run = await db.get(AppRuns, run_id)
        params = AppRunParams(
            id=run.id,
            user_id=run.user_id,
            app_id=run.app_id,
            file_ids=[UUID(file_id)],
            text=None,
        )
        return run.job_id, params


@pytest.mark.parametrize(
    "provider_failed", [False, True], ids=["complete-write", "failure-write"]
)
async def test_failed_terminal_write_rolls_back_and_announces_persisted_failure(
    queued_recording,
    client,
    db_session,
    admin_user_api_key,
    monkeypatch,
    provider_failed,
):
    job_id, params = queued_recording

    async def run_app(service, **kwargs):
        if provider_failed:
            raise RuntimeError("Summary unavailable")
        await service.repo.session.execute(
            sa.update(AppRuns)
            .where(AppRuns.id == params.id)
            .values(output_text="summary")
        )

    monkeypatch.setattr(AppRunService, "run_app", run_app)
    original_update = JobRepository.update_job
    terminal_writes = []

    async def update_job(repo, id, job, **kwargs):
        if id == job_id and job.status in (Status.COMPLETE, Status.FAILED):
            terminal_writes.append(job.status)
            if len(terminal_writes) == 1:
                # A rejected statement aborts the execution transaction in PostgreSQL.
                await repo.delegate.session.execute(sa.text("SELECT 1 / 0"))
        return await original_update(repo, id, job, **kwargs)

    monkeypatch.setattr(JobRepository, "update_job", update_job)
    terminal_events = []

    async def observe_committed_state(channel, message):
        if message.status in (Status.COMPLETE, Status.FAILED):
            async with db_session() as reader:
                job = await reader.get(Jobs, job_id)
                run = await reader.get(AppRuns, params.id)
                terminal_events.append((message.status, job.status, run.output_text))

    monkeypatch.setattr(task_manager, "publish_task_status", observe_committed_state)
    with suppress(sa.exc.DBAPIError):
        await app_run_worker.run_app({"job_id": str(job_id)}, params)

    detail = await client.get(
        f"/api/v1/app-runs/{params.id}/", headers={"X-API-Key": admin_user_api_key.key}
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == Status.FAILED
    assert terminal_events == [(Status.FAILED, Status.FAILED, None)]
    assert terminal_writes == [
        Status.FAILED if provider_failed else Status.COMPLETE,
        Status.FAILED,
    ]


async def test_poll_observes_status_and_summary_from_the_same_commit(
    app_run_fixture, client, db_session, admin_user_api_key
):
    job_id, params, _ = await app_run_fixture(status=Status.IN_PROGRESS)
    url = f"/api/v1/app-runs/{params.id}/"
    headers = {"X-API-Key": admin_user_api_key.key}

    async def finish_run(_driver):
        async with db_session() as writer:
            await writer.execute(
                sa.update(AppRuns)
                .where(AppRuns.id == params.id)
                .values(output_text="summary")
            )
            await writer.execute(
                sa.update(Jobs)
                .where(Jobs.id == job_id)
                .values(status=Status.COMPLETE.value)
            )

    committed = False

    def commit_after_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal committed
        # Finish the run after PostgreSQL has read the output, before ORM relationship loads.
        if (
            not committed
            and statement.startswith("SELECT")
            and "app_runs.output_text" in statement
        ):
            committed = True
            conn.connection.dbapi_connection.run_async(finish_run)

    async with db_session() as session:
        engine = session.bind.sync_engine
        sa.event.listen(engine, "after_cursor_execute", commit_after_read)
        try:
            first = await client.get(url, headers=headers)
        finally:
            sa.event.remove(engine, "after_cursor_execute", commit_after_read)
    assert committed
    assert first.status_code == 200, first.text
    assert (first.json()["status"], first.json()["output"]) == (
        Status.IN_PROGRESS,
        None,
    )

    latest = await client.get(url, headers=headers)
    assert latest.status_code == 200, latest.text
    assert (latest.json()["status"], latest.json()["output"]) == (
        Status.COMPLETE,
        "summary",
    )


async def test_app_worker_loss_before_completion_does_not_replay_started_work(
    app_run_fixture, db_session, client, monkeypatch
):
    job_id, params, _ = await app_run_fixture()
    delivery = {"job_id": str(job_id)}

    class LostWorker(BaseException):
        """Roll back execution without invoking the worker's graceful-failure handler."""

    start_app = AsyncMock(side_effect=LostWorker)
    monkeypatch.setattr(AppService, "get_app", start_app)
    with pytest.raises(LostWorker):
        await app_run_worker.run_app(delivery, params)

    async with db_session() as observer:
        job = await observer.get(Jobs, job_id)
        assert job is not None and job.status == Status.IN_PROGRESS.value

    assert await app_run_worker.run_app(delivery, params) is False
    start_app.assert_awaited_once_with(params.app_id)


@pytest.mark.parametrize(
    "failure_point", ["before_update", "other_worker", "after_commit"]
)
async def test_claim_error_fails_only_an_unstarted_app_run(
    app_run_fixture, db_session, client, admin_user_api_key, monkeypatch, failure_point
):
    job_id, params, _ = await app_run_fixture()
    claim = JobRepository.mark_job_started

    async def interrupted_claim(repo, id, **kwargs):
        if failure_point == "after_commit":
            dialect = repo.delegate.session.get_bind().dialect
            commit = dialect.do_commit

            def lose_ack(connection):
                monkeypatch.setattr(dialect, "do_commit", commit)
                commit(connection)
                raise ConnectionError("lost commit acknowledgement")

            monkeypatch.setattr(dialect, "do_commit", lose_ack)
            return await claim(repo, id, **kwargs)
        if failure_point == "other_worker":
            async with db_session() as other_worker:
                assert await claim(JobRepository(other_worker), id)
        raise ConnectionError("database connection interrupted")

    monkeypatch.setattr(JobRepository, "mark_job_started", interrupted_claim)
    start_app = AsyncMock()
    monkeypatch.setattr(AppService, "get_app", start_app)
    publish = AsyncMock()
    monkeypatch.setattr("eneo.worker.worker.publish_task_status", publish)

    with pytest.raises(ConnectionError):
        await app_run_worker.run_app({"job_id": str(job_id)}, params)

    response = await client.get(
        f"/api/v1/app-runs/{params.id}/", headers={"X-API-Key": admin_user_api_key.key}
    )
    assert response.status_code == 200, response.text
    start_app.assert_not_awaited()
    if failure_point != "before_update":
        assert response.json()["status"] == Status.IN_PROGRESS.value
        publish.assert_not_awaited()
        if failure_point == "after_commit":
            async with db_session() as recovery:
                assert job_id not in await reconcile_app_runs(
                    recovery, now=datetime.now(timezone.utc) + timedelta(minutes=4)
                )
                assert job_id in await reconcile_app_runs(
                    recovery, now=datetime.now(timezone.utc) + timedelta(minutes=6)
                )
    else:
        assert response.json()["status"] == Status.FAILED.value
        publish.assert_awaited_once_with(
            Channel(type=ChannelType.APP_RUN_UPDATES, user_id=params.user_id),
            RedisMessage(id=params.id, status=Status.FAILED),
        )


async def test_cancelled_app_run_fails_after_its_start_is_committed(
    app_run_fixture, db_session, client, monkeypatch
):
    job_id, params, _ = await app_run_fixture()
    monkeypatch.setattr(
        AppService, "get_app", AsyncMock(side_effect=asyncio.CancelledError)
    )

    with pytest.raises(asyncio.CancelledError):
        await app_run_worker.run_app({"job_id": str(job_id)}, params)

    async with db_session() as observer:
        job = await observer.get(Jobs, job_id)
        assert job is not None and job.status == Status.FAILED.value
        assert job.failure_code == JobFailureCode.CANCELLED.value


async def test_app_worker_stops_if_recovery_wins_between_claim_and_execution(
    app_run_fixture, db_session, monkeypatch
):
    job_id, params, _ = await app_run_fixture()
    touch = JobRepository.touch_job

    async def recover_before_execution(repo, id):
        async with db_session() as recovery:
            failed = await JobRepository(recovery).mark_stale_jobs_failed(
                tasks=[Task.RUN_APP.value],
                stale_before=datetime.now(timezone.utc) + timedelta(seconds=1),
                failure_code=JobFailureCode.PROCESSING_INTERRUPTED,
            )
            assert id in failed
        return await touch(repo, id)

    monkeypatch.setattr(JobRepository, "touch_job", recover_before_execution)
    start_app = AsyncMock()
    monkeypatch.setattr(AppService, "get_app", start_app)
    assert await app_run_worker.run_app({"job_id": str(job_id)}, params) is False
    start_app.assert_not_awaited()
    async with db_session() as observer:
        job = await observer.get(Jobs, job_id)
        assert job is not None and job.status == Status.FAILED.value


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

    async with redis_client.pubsub() as subscription:
        await subscription.subscribe(channel.channel_string)
        await subscription.get_message(timeout=2)  # Acknowledge subscription.
        async with db_session() as running:
            assert await JobRepository(running).mark_job_started(active)
            reaping = asyncio.create_task(_run_app_maintenance())
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


async def test_retry_backlog_does_not_hide_interrupted_or_expired_results(
    app_run_fixture, db_session, client, admin_user_api_key, monkeypatch
):
    from eneo.apps.app_runs.app_run_dispatch import APP_RUN_RECOVERY_BATCH

    now = datetime.now(timezone.utc)
    retry_ids = []
    for _ in range(APP_RUN_RECOVERY_BATCH):
        job_id, _, _ = await app_run_fixture()
        retry_ids.append(job_id)
    _, interrupted, _ = await app_run_fixture(
        status=Status.IN_PROGRESS, age=timedelta(minutes=6)
    )
    expired_id, expired, _ = await app_run_fixture()
    envelope = {"version": 1, "file_ids": []}
    async with db_session() as session:
        await session.execute(
            sa.update(Jobs)
            .where(Jobs.id.in_(retry_ids))
            .values(dispatch_envelope=envelope, updated_at=now - timedelta(minutes=15))
        )
        await session.execute(
            sa.update(Jobs)
            .where(Jobs.id == expired_id)
            .values(
                dispatch_envelope=envelope,
                created_at=now - timedelta(hours=2, minutes=1),
                updated_at=now - timedelta(minutes=1),
            )
        )

    broker = AsyncMock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr(job_manager, "redispatch_app", broker)
    await _run_app_maintenance()
    broker.assert_awaited_once()
    for run in (interrupted, expired):
        detail = await client.get(
            f"/api/v1/app-runs/{run.id}/", headers={"X-API-Key": admin_user_api_key.key}
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == Status.FAILED


async def test_recovery_deadline_survives_redis_outage_and_refuses_late_delivery(
    app_run_fixture, db_session, monkeypatch, client, admin_user_api_key
):
    job_id, params, _ = await app_run_fixture(age=timedelta(minutes=6))
    deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    now = deadline - timedelta(minutes=10)
    async with db_session() as session:
        await session.execute(
            sa.update(Jobs)
            .where(Jobs.id == job_id)
            .values(
                dispatch_envelope={"version": 1, "file_ids": []},
                created_at=now - timedelta(minutes=110),
                updated_at=now - timedelta(minutes=6),
            )
        )
    attempt = AsyncMock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr(job_manager, "redispatch_app", attempt)
    async with db_session() as session:
        assert await reconcile_app_runs(session, now=now) == []
    attempt.assert_awaited_once()
    attempt.side_effect = None
    async with db_session() as session:
        assert (
            await reconcile_app_runs(session, now=deadline - timedelta(minutes=1)) == []
        )
    assert attempt.await_count == 2
    async with db_session() as session:
        assert not await claim_app_job(JobRepository(session), job_id)
        assert await reconcile_app_runs(session, now=deadline) == [job_id]
        assert await session.scalar(
            sa.select(Jobs.dispatch_envelope.is_(None)).where(Jobs.id == job_id)
        )
    assert attempt.await_count == 2
    detail = await client.get(
        f"/api/v1/app-runs/{params.id}/", headers={"X-API-Key": admin_user_api_key.key}
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == Status.FAILED


@pytest.mark.parametrize("removed", [False, True], ids=["invalid-file", "deleted-run"])
async def test_recovery_rejects_missing_source_without_republishing(
    app_run_fixture, db_session, monkeypatch, removed
):
    job_id, params, _ = await app_run_fixture(age=timedelta(minutes=6))
    async with db_session() as session:
        await session.execute(
            sa.update(Jobs)
            .where(Jobs.id == job_id)
            .values(
                dispatch_envelope={"version": 1, "file_ids": [str(uuid4())]},
                updated_at=datetime.now(timezone.utc) - timedelta(minutes=6),
            )
        )
        if removed:
            await session.execute(sa.delete(AppRuns).where(AppRuns.id == params.id))
    broker = AsyncMock()
    monkeypatch.setattr(job_manager, "redispatch_app", broker)
    await _run_app_maintenance()
    async with db_session() as session:
        job = await session.get(Jobs, job_id)
        assert job.status == Status.FAILED
        assert job.failure_code == JobFailureCode.INVALID_JOB_PAYLOAD
        assert job.dispatch_envelope is None
    broker.assert_not_awaited()


@pytest.mark.parametrize("committed", [False, True], ids=["rollback", "lost-ack"])
async def test_checkpoint_failure_stops_before_summary_and_records_actual_progress(
    client, db_session, admin_user_api_key, queued_recording, monkeypatch, committed
):
    from eneo.files.file_service import FileService
    from eneo.worker.task_manager import JobCheckpointError

    job_id, params = queued_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    async with db_session() as db:
        dialect = db.get_bind().dialect

    save = FileService.save_transcription
    commit = dialect.do_commit

    async def interrupt_checkpoint(self, *args):
        result = await save(self, *args)

        def interrupted(connection):
            monkeypatch.setattr(dialect, "do_commit", commit)
            if committed:
                commit(connection)
            else:
                connection.rollback()
            raise ConnectionError("checkpoint acknowledgement unavailable")

        monkeypatch.setattr(dialect, "do_commit", interrupted)
        return result

    monkeypatch.setattr(FileService, "save_transcription", interrupt_checkpoint)
    monkeypatch.setattr(
        Transcriber, "transcribe_from_filepath", AsyncMock(return_value="saved speech")
    )
    summary = AsyncMock()
    monkeypatch.setattr(CompletionService, "get_response", summary)
    with pytest.raises(JobCheckpointError):
        await app_run_worker.run_app({"job_id": job_id}, params)
    summary.assert_not_awaited()
    detail = await client.get(f"/api/v1/app-runs/{params.id}/", headers=headers)
    assert detail.json()["status"] == Status.FAILED
    assert detail.json()["input"]["files"][0]["transcription"] == (
        "saved speech" if committed else None
    )


async def test_recovery_skips_a_live_worker_between_checkpoint_transactions(
    client,
    db_session,
    admin_user_api_key,
    recovery_recording,
    monkeypatch,
    test_settings,
):
    app_url, file_id, _ = recovery_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    submitted = await client.post(
        f"{app_url}runs/", json={"files": [{"id": file_id}]}, headers=headers
    )
    assert submitted.status_code == 203, submitted.text
    async with db_session() as db:
        run = await db.get(AppRuns, UUID(submitted.json()["id"]))
        params = AppRunParams(
            id=run.id,
            user_id=run.user_id,
            app_id=run.app_id,
            file_ids=[UUID(file_id)],
            text=None,
        )
        job_id = run.job_id

    returned_at = None

    async def transcribe(*args, **kwargs):
        nonlocal returned_at
        returned_at = datetime.now(timezone.utc)
        return "speech"

    async def complete(self, *, model, **kwargs):
        return CompletionModelResponse(
            completion=Completion(text="summary"), model=model, total_token_count=1
        )

    touch = JobRepository.touch_job
    touches = 0

    async def observe_checkpoint(self, id):
        nonlocal touches
        touches += 1
        if touches == 3:
            async with db_session() as observer:
                seen = await observer.get(Jobs, id)
                assert returned_at is not None and seen.updated_at >= returned_at
                assert id not in await reconcile_app_runs(observer)
        return await touch(self, id)

    monkeypatch.setattr(Transcriber, "transcribe_from_filepath", transcribe)
    monkeypatch.setattr(CompletionService, "get_response", complete)
    monkeypatch.setattr(JobRepository, "touch_job", observe_checkpoint)
    from eneo.database.database import DatabaseSessionManager
    from eneo.worker import worker as worker_module

    worker_db = DatabaseSessionManager()
    settings = test_settings.model_copy(
        update={"db_pool_size": 1, "db_pool_max_overflow": 0, "db_pool_timeout": 2}
    )
    monkeypatch.setattr("eneo.database.database.get_settings", lambda: settings)
    worker_db.init(settings.database_url)
    monkeypatch.setattr(worker_module, "sessionmanager", worker_db)
    try:
        assert await app_run_worker.run_app({"job_id": job_id}, params)
        assert touches == 3
    finally:
        await worker_db.close()


async def test_deleting_a_queued_run_cancels_dispatch_and_removes_its_only_file(
    db_session, client, admin_user_api_key, recovery_recording
):
    url, file_id, _ = recovery_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    response = await client.post(
        url + "runs/", json={"files": [{"id": file_id}]}, headers=headers
    )
    run_id = UUID(response.json()["id"])
    async with db_session() as session:
        job_id = (await session.get(AppRuns, run_id)).job_id
    deleted = await client.delete(f"/api/v1/app-runs/{run_id}/", headers=headers)
    assert deleted.status_code == 204, deleted.text
    async with db_session() as session:
        job = await session.get(Jobs, job_id)
        assert (
            job.status == Status.FAILED and job.failure_code == JobFailureCode.CANCELLED
        )
        assert job.dispatch_envelope is None
        assert not await claim_app_job(JobRepository(session), job_id)
    source = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
    assert source.status_code == 404, source.text


async def test_recovered_text_run_reads_its_original_prompt_from_the_run(
    client, db_session, admin_user_api_key, recovery_recording, monkeypatch
):
    url, _, _ = recovery_recording
    headers = {"X-API-Key": admin_user_api_key.key}
    setup = await client.patch(
        url, json={"input_fields": [{"type": "text-field"}]}, headers=headers
    )
    assert setup.status_code == 200, setup.text
    prompt = "Summarize the planning meeting"
    with monkeypatch.context() as stopped_api:
        stopped_api.setattr(
            "eneo.jobs.job_service.after_outer_transaction",
            lambda *args, **kwargs: None,
        )
        response = await client.post(
            url + "runs/", json={"text": prompt}, headers=headers
        )
    assert response.status_code == 203, response.text
    async with db_session() as session:
        run = await session.get(AppRuns, UUID(response.json()["id"]))
        assert run.input_text == prompt
        job = await session.get(Jobs, run.job_id)
        assert job.dispatch_envelope == {"version": 1, "file_ids": []}
        job_id = job.id
        job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    async with db_session() as session:
        assert await reconcile_app_runs(session) == []
    assert job_manager._redis is not None
    info = await ArqJob(str(job_id), redis=job_manager._redis).info()
    assert info and info.args[0].text is None

    async def complete(self, *, model, text_input, **kwargs):
        assert text_input == prompt
        return CompletionModelResponse(
            completion=Completion(text="summary"), model=model, total_token_count=1
        )

    monkeypatch.setattr(CompletionService, "get_response", complete)
    assert await app_run_worker.run_app({"job_id": job_id}, info.args[0])


@pytest.mark.parametrize("redispatch", [False, True], ids=["submission", "recovery"])
async def test_app_delivery_returns_its_connection_after_a_broker_stall(
    test_settings, redis_client, monkeypatch, redispatch
):
    from redis.asyncio.client import Pipeline

    from eneo.jobs import job_manager as queues

    settings = test_settings.model_copy(
        update={
            "redis_conn_timeout": 1,
            "redis_retry_on_timeout": False,
            "redis_max_connections": 1,
        }
    )
    monkeypatch.setattr(queues, "get_settings", lambda: settings)
    manager = queues.JobManager()
    await manager.init()
    try:
        paused = asyncio.Event()
        watch = Pipeline.watch

        async def pause_after_watch(self, *names):
            answer = await watch(self, *names)
            await redis_client.execute_command("CLIENT", "PAUSE", 10_000, "ALL")
            paused.set()
            return answer

        params = AppRunParams(
            id=uuid4(), app_id=uuid4(), file_ids=[], user_id=uuid4(), text=None
        )
        # Pause the test Redis after WATCH so both the enqueue and its pipeline cleanup stall.
        with monkeypatch.context() as stop:
            stop.setattr(Pipeline, "watch", pause_after_watch)
            delivery = (
                manager.redispatch_app(uuid4(), params)
                if redispatch
                else manager.enqueue(Task.RUN_APP, uuid4(), params)
            )
            request = asyncio.create_task(delivery)
            try:
                await asyncio.wait_for(paused.wait(), 5)
                done, _ = await asyncio.wait([request], timeout=4)
            finally:
                await redis_client.execute_command("CLIENT", "UNPAUSE")
                await asyncio.gather(request, return_exceptions=True)
            assert request in done
        assert (
            await asyncio.wait_for(manager.enqueue(Task.RUN_APP, uuid4(), params), 4)
            is not None
        )
    finally:
        await manager.close()
