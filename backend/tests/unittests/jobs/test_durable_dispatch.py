import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from arq.worker import Function
from sqlalchemy.orm import Session

from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_service import JobService
from eneo.jobs.task_models import UploadInfoBlob, build_dispatch_envelope
from eneo.main.models import Status
from tests.fixtures import TEST_USER


def _params() -> UploadInfoBlob:
    return UploadInfoBlob(
        user_id=TEST_USER.id,
        group_id=uuid4(),
        space_id=uuid4(),
        filename="document.txt",
        mimetype="text/plain",
    )


async def test_restart_safe_dispatch_is_scheduled_only_after_commit(
    monkeypatch,
) -> None:
    session = Session()
    repo = MagicMock()
    repo.delegate.session.sync_session = session
    job_id = uuid4()
    repo.add_restart_safe_job = AsyncMock(
        return_value=JobInDb(
            id=job_id,
            user_id=TEST_USER.id,
            task=Task.UPLOAD_FILE,
            name="document.txt",
            status=Status.QUEUED,
        )
    )
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    params = _params()

    with session.begin():
        await JobService(TEST_USER, repo).queue_restart_safe_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=params,
            job_id=job_id,
        )
        enqueue.assert_not_awaited()

    await asyncio.sleep(0)
    enqueue.assert_awaited_once_with(Task.UPLOAD_FILE, job_id, params)


def test_durable_envelope_has_no_filesystem_path() -> None:
    envelope = build_dispatch_envelope(Task.UPLOAD_FILE, _params())

    assert "filepath" not in envelope.model_dump(mode="json")["params"]


def test_durable_worker_functions_do_not_retain_arq_results() -> None:
    from eneo.worker.routes import worker

    durable_functions = {
        function.name: function
        for function in worker.functions
        if isinstance(function, Function)
        and function.name in {Task.UPLOAD_FILE.value, Task.TRANSCRIPTION.value}
    }

    assert set(durable_functions) == {
        Task.UPLOAD_FILE.value,
        Task.TRANSCRIPTION.value,
    }
    assert all(function.keep_result_s == 0 for function in durable_functions.values())
