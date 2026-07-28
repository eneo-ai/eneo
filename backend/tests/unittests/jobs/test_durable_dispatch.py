import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from arq.worker import Function
from pydantic import BaseModel
from sqlalchemy.orm import Session

from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_serialization import deserialize_job
from eneo.jobs.job_service import JobService
from eneo.jobs.task_models import (
    Transcription,
    UploadInfoBlob,
    build_dispatch_envelope,
)
from eneo.main.models import Status
from tests.fixtures import TEST_USER

_FROZEN_LEGACY_UPLOAD_JOB = base64.b64decode(
    "gASVoQEAAAAAAAB9lCiMAXSUSwGMAWaUjBRlbmVvLmpvYnMuam9iX21vZGVsc5SMBFRhc2uU"
    "k5SMEHVwbG9hZF9pbmZvX2Jsb2KUhZRSlIwBYZSMFWVuZW8uam9icy50YXNrX21vZGVsc5SM"
    "DlVwbG9hZEluZm9CbG9ilJOUKYGUfZQojAhfX2RpY3RfX5R9lCiMB3VzZXJfaWSUjAR1dWlk"
    "lIwEVVVJRJSTlCmBlH2UjANpbnSUSwFzYowIZ3JvdXBfaWSUaBQpgZR9lGgXSwJzYowIc3Bh"
    "Y2VfaWSUaBQpgZR9lGgXSwNzYowIZmlsZW5hbWWUjApsZWdhY3kudHh0lIwIbWltZXR5cGWU"
    "jAp0ZXh0L3BsYWlulIwIZmlsZXBhdGiUjBcvdG1wL2xlZ2FjeS11cGxvYWQtcGF0aJR1jBJf"
    "X3B5ZGFudGljX2V4dHJhX1+UTowXX19weWRhbnRpY19maWVsZHNfc2V0X1+Uj5QoaBhoEWgb"
    "aCJoIGgekIwUX19weWRhbnRpY19wcml2YXRlX1+UTnVihZSMAWuUfZSMAmV0lEsAdS4="
)


class _OldUploadTaskContract(BaseModel):
    user_id: UUID
    group_id: UUID
    space_id: UUID
    filepath: str
    filename: str
    mimetype: str


def _params() -> UploadInfoBlob:
    return UploadInfoBlob(
        user_id=TEST_USER.id,
        group_id=uuid4(),
        space_id=uuid4(),
        filename="document.txt",
        mimetype="text/plain",
    )


def _repo(session: Session, job_id: UUID) -> MagicMock:
    repo = MagicMock()
    repo.delegate.session.sync_session = session
    repo.add_durable_knowledge_job = AsyncMock(
        return_value=JobInDb(
            id=job_id,
            user_id=TEST_USER.id,
            task=Task.UPLOAD_FILE,
            name="document.txt",
            status=Status.QUEUED,
        )
    )
    return repo


async def test_durable_dispatch_is_scheduled_only_after_commit(
    monkeypatch,
) -> None:
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    params = _params()

    with session.begin():
        await JobService(TEST_USER, repo).queue_durable_knowledge_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=params,
            job_id=job_id,
        )
        enqueue.assert_not_awaited()

    await asyncio.sleep(0)
    enqueue.assert_awaited_once_with(Task.UPLOAD_FILE, job_id, params)
    dispatched_params = enqueue.await_args.args[2]
    assert getattr(dispatched_params, "filepath").endswith(f"/job-staging/{job_id}")


async def test_savepoint_commit_then_outer_rollback_never_dispatches(
    monkeypatch,
) -> None:
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)

    outer = session.begin()
    await JobService(TEST_USER, repo).queue_durable_knowledge_job(
        Task.UPLOAD_FILE,
        name="document.txt",
        task_params=_params(),
        job_id=job_id,
    )
    with session.begin_nested():
        pass
    await asyncio.sleep(0)
    outer.rollback()

    enqueue.assert_not_awaited()


async def test_outer_rollback_then_unrelated_commit_never_dispatches(
    monkeypatch,
) -> None:
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)

    outer = session.begin()
    await JobService(TEST_USER, repo).queue_durable_knowledge_job(
        Task.UPLOAD_FILE,
        name="document.txt",
        task_params=_params(),
        job_id=job_id,
    )
    outer.rollback()
    with session.begin():
        pass
    await asyncio.sleep(0)

    enqueue.assert_not_awaited()


async def test_outer_rollback_removes_staged_file_and_never_dispatches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from eneo.jobs import job_staging

    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    staged_file = job_staging.job_staging_path(job_id)
    staged_file.parent.mkdir(parents=True)
    staged_file.write_bytes(b"pending upload")

    outer = session.begin()
    await JobService(TEST_USER, repo).queue_durable_knowledge_job(
        Task.UPLOAD_FILE,
        name="document.txt",
        task_params=_params(),
        job_id=job_id,
    )
    outer.rollback()
    await asyncio.sleep(0)

    assert not staged_file.exists()
    enqueue.assert_not_awaited()


async def test_outer_commit_keeps_staged_file_for_worker_and_dispatches_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from eneo.jobs import job_staging

    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    staged_file = job_staging.job_staging_path(job_id)
    staged_file.parent.mkdir(parents=True)
    staged_file.write_bytes(b"pending upload")

    with session.begin():
        await JobService(TEST_USER, repo).queue_durable_knowledge_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=_params(),
            job_id=job_id,
        )
    await asyncio.sleep(0)

    assert staged_file.read_bytes() == b"pending upload"
    assert enqueue.await_count == 1


async def test_savepoint_then_outer_commit_dispatches_once(monkeypatch) -> None:
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    params = _params()

    with session.begin():
        await JobService(TEST_USER, repo).queue_durable_knowledge_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=params,
            job_id=job_id,
        )
        with session.begin_nested():
            pass
        await asyncio.sleep(0)
        enqueue.assert_not_awaited()

    await asyncio.sleep(0)
    enqueue.assert_awaited_once_with(Task.UPLOAD_FILE, job_id, params)


async def test_durable_queue_rejects_creation_inside_savepoint() -> None:
    session = Session()
    repo = _repo(session, uuid4())

    with session.begin():
        with session.begin_nested():
            with pytest.raises(ValueError, match="nested transaction"):
                await JobService(TEST_USER, repo).queue_durable_knowledge_job(
                    Task.UPLOAD_FILE,
                    name="document.txt",
                    task_params=_params(),
                )

    repo.add_durable_knowledge_job.assert_not_awaited()


async def test_immediate_session_reuse_dispatches_exactly_once(monkeypatch) -> None:
    session = Session()
    job_id = uuid4()
    repo = _repo(session, job_id)
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)

    with session.begin():
        await JobService(TEST_USER, repo).queue_durable_knowledge_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=_params(),
            job_id=job_id,
        )
    with session.begin():
        pass

    await asyncio.sleep(0)
    assert enqueue.await_count == 1


async def test_durable_queue_rejects_mismatched_user_before_persisting() -> None:
    session = Session()
    repo = _repo(session, uuid4())
    params = _params().model_copy(update={"user_id": uuid4()})

    with pytest.raises(ValueError, match="user"):
        await JobService(TEST_USER, repo).queue_durable_knowledge_job(
            Task.UPLOAD_FILE,
            name="document.txt",
            task_params=params,
        )

    repo.add_durable_knowledge_job.assert_not_awaited()


def test_durable_envelope_has_no_filesystem_path() -> None:
    envelope = build_dispatch_envelope(Task.UPLOAD_FILE, _params())

    assert "filepath" not in envelope.model_dump(mode="json")["params"]


def test_new_worker_uses_path_from_frozen_legacy_payload() -> None:
    from eneo.worker.upload_tasks import _job_file_path

    decoded = deserialize_job(_FROZEN_LEGACY_UPLOAD_JOB)
    args = decoded["a"]
    assert isinstance(args, tuple)
    params = args[0]
    assert isinstance(params, UploadInfoBlob)

    assert _job_file_path(uuid4(), params) == Path("/tmp/legacy-upload-path")


@pytest.mark.parametrize(
    ("task", "params_type"),
    [
        (Task.UPLOAD_FILE, UploadInfoBlob),
        (Task.TRANSCRIPTION, Transcription),
    ],
)
def test_new_dispatch_payload_satisfies_old_worker_contract(
    task: Task,
    params_type: type[UploadInfoBlob] | type[Transcription],
) -> None:
    from eneo.jobs.durable_dispatch import build_knowledge_dispatch_params

    params = params_type(**_params().model_dump())
    job_id = uuid4()
    compatible = build_knowledge_dispatch_params(params, job_id)

    old_payload = _OldUploadTaskContract.model_validate(compatible.__dict__)
    assert old_payload.filepath.endswith(f"/job-staging/{job_id}")


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
