from tempfile import SpooledTemporaryFile
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_size_service import FileSizeService
from eneo.jobs.job_models import Task
from eneo.jobs.task_service import TaskService
from eneo.main.exceptions import FileTooLargeException, InvalidFilenameException
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from tests.fixtures import TEST_USER

_UPLOAD_ADMISSION = UploadAdmissionSnapshot(
    policy_revision=3,
    new_write_storage_target=StorageKind.OBJECT_STORE,
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
    from eneo.jobs import job_staging

    settings = SimpleNamespace(upload_tmp_dir=tmp_upload_dir)
    monkeypatch.setattr(fss_module, "get_settings", lambda: settings)
    monkeypatch.setattr(job_staging, "get_settings", lambda: settings)
    return FileSizeService()


@pytest.fixture
def job_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def object_content():
    return AsyncMock()


@pytest.fixture
def task_service(file_size_service, job_service, object_content):
    return TaskService(
        user=TEST_USER,
        file_size_service=file_size_service,
        job_service=job_service,
        object_content=object_content,
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
    job_service.queue_durable_knowledge_job.side_effect = RuntimeError("queue down")

    with pytest.raises(RuntimeError, match="queue down"):
        await task_service.queue_upload_file(
            group_id=uuid4(),
            space_id=uuid4(),
            file=_make_file(),
            mimetype="text/plain",
            filename="test.txt",
        )

    remaining = [path for path in tmp_upload_dir.rglob("*") if path.is_file()]
    assert remaining == []


async def test_queue_upload_file_preserves_file_on_success(
    task_service, job_service, object_content, tmp_upload_dir
):
    job_service.queue_durable_knowledge_job.return_value = MagicMock()

    await task_service.queue_upload_file(
        group_id=uuid4(),
        space_id=uuid4(),
        file=_make_file(),
        mimetype="text/plain",
        filename="test.txt",
    )

    remaining = [path for path in tmp_upload_dir.rglob("*") if path.is_file()]
    assert len(remaining) == 1
    assert remaining[0].read_bytes() == b"test data"
    call = job_service.queue_durable_knowledge_job.await_args
    assert call is not None
    params = call.kwargs["task_params"]
    assert "filepath" not in params.model_dump()
    assert params.filename == "test.txt"
    assert params.original_storage.policy_revision == _UPLOAD_ADMISSION.policy_revision
    assert (
        params.original_storage.storage_target
        is _UPLOAD_ADMISSION.new_write_storage_target
    )
    assert (
        params.original_storage.maximum_bytes
        == _UPLOAD_ADMISSION.knowledge_file_maximum_bytes
    )
    object_content.ensure_target_ready.assert_awaited_once_with(
        StorageKind.OBJECT_STORE
    )
    assert remaining[0].name == str(call.kwargs["job_id"])


async def test_queue_upload_file_sanitizes_filename_before_job_creation(
    task_service, job_service
) -> None:
    job_service.queue_durable_knowledge_job.return_value = MagicMock()

    await task_service.queue_upload_file(
        group_id=uuid4(),
        space_id=uuid4(),
        file=_make_file(),
        mimetype="text/plain",
        filename="../folder/\x00 report.txt ",
    )

    call = job_service.queue_durable_knowledge_job.await_args
    assert call is not None
    assert call.kwargs["name"] == "report.txt"
    assert call.kwargs["task_params"].filename == "report.txt"


@pytest.mark.parametrize("filename", ["", " \x00 ", "x" * 256])
async def test_queue_upload_file_rejects_invalid_filename_before_staging(
    task_service,
    job_service,
    object_content,
    tmp_upload_dir,
    filename: str,
) -> None:
    with pytest.raises(InvalidFilenameException):
        await task_service.queue_upload_file(
            group_id=uuid4(),
            space_id=uuid4(),
            file=_make_file(),
            mimetype="text/plain",
            filename=filename,
        )

    assert list(tmp_upload_dir.rglob("*")) == []
    job_service.queue_durable_knowledge_job.assert_not_awaited()
    object_content.ensure_target_ready.assert_not_awaited()


async def test_queue_upload_file_checks_target_readiness_before_staging(
    task_service,
    job_service,
    object_content,
    tmp_upload_dir,
) -> None:
    object_content.ensure_target_ready.side_effect = RuntimeError("storage unavailable")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await task_service.queue_upload_file(
            group_id=uuid4(),
            space_id=uuid4(),
            file=_make_file(),
            mimetype="text/plain",
            filename="test.txt",
        )

    assert list(tmp_upload_dir.rglob("*")) == []
    job_service.queue_durable_knowledge_job.assert_not_awaited()
