from tempfile import SpooledTemporaryFile
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.files.file_size_service import FileSizeService
from intric.jobs.task_service import TaskService
from tests.fixtures import TEST_USER


@pytest.fixture
def tmp_upload_dir(tmp_path):
    return tmp_path


@pytest.fixture
def file_size_service(tmp_upload_dir, monkeypatch):
    from intric.files import file_size_service as fss_module

    from types import SimpleNamespace

    settings = SimpleNamespace(upload_tmp_dir=tmp_upload_dir)
    monkeypatch.setattr(fss_module, "get_settings", lambda: settings)
    return FileSizeService()


@pytest.fixture
def job_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def quota_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def task_service(file_size_service, job_service, quota_service):
    return TaskService(
        user=TEST_USER,
        file_size_service=file_size_service,
        job_service=job_service,
        quota_service=quota_service,
    )


def _make_file(content: bytes = b"test data") -> SpooledTemporaryFile:
    f = SpooledTemporaryFile()
    f.write(content)
    f.seek(0)
    return f


async def test_queue_upload_file_cleans_up_on_queue_failure(
    task_service, job_service, tmp_upload_dir
):
    job_service.queue_job.side_effect = RuntimeError("queue down")

    with pytest.raises(RuntimeError, match="queue down"):
        await task_service.queue_upload_file(
            group_id=uuid4(),
            space_id=uuid4(),
            file=_make_file(),
            mimetype="text/plain",
            filename="test.txt",
        )

    remaining = list(tmp_upload_dir.iterdir())
    assert remaining == []


async def test_queue_upload_file_preserves_file_on_success(
    task_service, job_service, tmp_upload_dir
):
    job_service.queue_job.return_value = MagicMock()

    await task_service.queue_upload_file(
        group_id=uuid4(),
        space_id=uuid4(),
        file=_make_file(),
        mimetype="text/plain",
        filename="test.txt",
    )

    remaining = list(tmp_upload_dir.iterdir())
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == b"test data"
