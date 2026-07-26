from tempfile import SpooledTemporaryFile
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_size_service import FileSizeService
from eneo.jobs.job_models import Task
from eneo.jobs.task_service import TaskService
from eneo.main.exceptions import FileTooLargeException
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from tests.fixtures import TEST_USER

_UPLOAD_ADMISSION = UploadAdmissionSnapshot(
    policy_revision=3,
    session_storage_target=StorageKind.POSTGRES_INLINE,
    session_operator_ceiling_bytes=100,
    session_file_maximum_bytes=7,
    session_image_maximum_bytes=8,
    session_audio_maximum_bytes=9,
    knowledge_file_maximum_bytes=10,
    knowledge_audio_maximum_bytes=12,
)


@pytest.fixture
def tmp_upload_dir(tmp_path):
    return tmp_path


@pytest.fixture
def file_size_service(tmp_upload_dir, monkeypatch):
    from types import SimpleNamespace

    from eneo.files import file_size_service as fss_module

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
        upload_admission=_UPLOAD_ADMISSION,
    )


def _make_file(content: bytes = b"test data") -> SpooledTemporaryFile:
    f = SpooledTemporaryFile()
    f.write(content)
    f.seek(0)
    return f


@pytest.mark.parametrize(
    ("task", "maximum_bytes"),
    [
        (Task.UPLOAD_FILE, _UPLOAD_ADMISSION.knowledge_file_maximum_bytes),
        (Task.TRANSCRIPTION, _UPLOAD_ADMISSION.knowledge_audio_maximum_bytes),
    ],
)
async def test_validate_file_size_accepts_policy_maximum(
    task_service: TaskService,
    task: Task,
    maximum_bytes: int,
) -> None:
    await task_service.validate_file_size(_make_file(b"x" * maximum_bytes), task)


@pytest.mark.parametrize(
    ("task", "maximum_bytes", "limit_name"),
    [
        (
            Task.UPLOAD_FILE,
            _UPLOAD_ADMISSION.knowledge_file_maximum_bytes,
            "knowledge_file",
        ),
        (
            Task.TRANSCRIPTION,
            _UPLOAD_ADMISSION.knowledge_audio_maximum_bytes,
            "knowledge_audio",
        ),
    ],
)
async def test_validate_file_size_rejects_policy_maximum_plus_one(
    task_service: TaskService,
    task: Task,
    maximum_bytes: int,
    limit_name: str,
) -> None:
    with pytest.raises(FileTooLargeException) as captured:
        await task_service.validate_file_size(
            _make_file(b"x" * (maximum_bytes + 1)),
            task,
        )

    assert captured.value.max_size == maximum_bytes
    assert captured.value.limit_name == limit_name


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
