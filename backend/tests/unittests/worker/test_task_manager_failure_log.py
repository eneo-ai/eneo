"""A failed job is logged and recorded by its kind and code: an exception's
message can quote what the job worked on, which retention removes and a log
or job record would keep."""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.jobs.job_models import JobFailureCode
from eneo.jobs.job_service import JobService
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.worker import task_manager as task_manager_module
from eneo.worker.task_manager import TaskManager
from tests.fixtures import TEST_USER

_PRIVATE = "Utredning om Anna Svensson"


@pytest.fixture
def job_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> pytest.LogCaptureFixture:
    monkeypatch.setattr(
        task_manager_module, "logger", logging.getLogger("eneo.test.task_manager")
    )
    caplog.set_level(logging.DEBUG, logger="eneo.test.task_manager")
    return caplog


def _task_manager() -> tuple[TaskManager, AsyncMock]:
    job_service = AsyncMock()
    manager = TaskManager(
        user=cast(Any, SimpleNamespace(id=uuid4())),
        job_id=uuid4(),
        job_service=job_service,
    )
    return manager, job_service


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    return caplog.text + "".join(repr(record.__dict__) for record in caplog.records)


def _fail_with_a_cause() -> None:
    try:
        raise ValueError(f"the provider echoed: {_PRIVATE}")
    except ValueError as error:
        raise RuntimeError(f"wrapped: {_PRIVATE}") from error


@pytest.mark.asyncio
async def test_a_failed_job_is_logged_and_recorded_without_its_message(
    job_log: pytest.LogCaptureFixture,
) -> None:
    manager, job_service = _task_manager()

    async with manager.set_status_on_exception(status_already_set=True):
        _fail_with_a_cause()

    assert manager.successful() is False
    job_service.fail_job.assert_awaited_once_with(
        manager.job_id, failure_code=JobFailureCode.PROCESSING_FAILED
    )
    logged = _logged(job_log)
    assert _PRIVATE not in logged
    (record,) = [r for r in job_log.records if r.levelno >= logging.ERROR]
    assert str(manager.job_id) in record.getMessage()
    assert "RuntimeError <- ValueError" in record.getMessage()
    assert record.__dict__["error_at"].endswith("in _fail_with_a_cause")
    assert record.exc_info is None


@pytest.mark.asyncio
async def test_a_typed_failure_is_recorded_by_its_code(
    job_log: pytest.LogCaptureFixture,
) -> None:
    manager, job_service = _task_manager()

    async with manager.set_status_on_exception(status_already_set=True):
        raise ObjectContentUnavailableError("store unavailable")

    job_service.fail_job.assert_awaited_once_with(
        manager.job_id, failure_code=JobFailureCode.STORAGE_UNAVAILABLE
    )
    assert "storage_unavailable" in job_log.text


@pytest.mark.asyncio
async def test_a_cancelled_job_is_recorded_as_cancelled(
    job_log: pytest.LogCaptureFixture,
) -> None:
    manager, job_service = _task_manager()

    with pytest.raises(asyncio.CancelledError):
        async with manager.set_status_on_exception(status_already_set=True):
            raise asyncio.CancelledError()

    job_service.fail_job.assert_awaited_once_with(
        manager.job_id, failure_code=JobFailureCode.CANCELLED
    )


@pytest.mark.asyncio
async def test_a_job_failure_is_stored_as_its_code_without_text() -> None:
    repo = MagicMock(update_job=AsyncMock())
    job_id = uuid4()

    await JobService(TEST_USER, repo).fail_job(
        job_id, failure_code=JobFailureCode.CORRUPT
    )

    stored = repo.update_job.await_args.args[1].model_dump(exclude_unset=True)
    assert stored["failure_code"] == JobFailureCode.CORRUPT
    assert stored["result_location"] is None
