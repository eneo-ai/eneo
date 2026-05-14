from uuid import uuid4

import pytest

from intric.main.models import Status
from intric.worker.task_manager import TaskManager
from tests.fixtures import TEST_USER


@pytest.mark.asyncio
async def test_status_context_reports_exception_before_marking_failed(
    monkeypatch: pytest.MonkeyPatch,
):
    events: list[str] = []
    failed_messages: list[str | None] = []

    async def on_exception(exc: BaseException) -> None:
        assert exc is expected_error
        events.append("on_exception")

    async def fail_job(message: str | None = None) -> None:
        failed_messages.append(message)
        events.append("fail_job")

    manager = TaskManager(user=TEST_USER, job_id=uuid4(), job_service=None)
    monkeypatch.setattr(manager, "fail_job", fail_job)

    expected_error = RuntimeError("crawler crashed")
    async with manager.set_status_on_exception(
        status_already_set=True,
        on_exception=on_exception,
    ):
        raise expected_error

    assert events == ["on_exception", "fail_job"]
    assert failed_messages == ["crawler crashed"]
    assert manager.successful() is False


@pytest.mark.asyncio
async def test_terminal_acknowledgement_suppresses_default_complete_publish(
    monkeypatch: pytest.MonkeyPatch,
):
    published_statuses: list[Status] = []

    async def publish_status(*, status: Status) -> None:
        published_statuses.append(status)

    manager = TaskManager(user=TEST_USER, job_id=uuid4(), job_service=None)
    monkeypatch.setattr(manager, "_publish_status", publish_status)

    async with manager.set_status_on_exception(status_already_set=True):
        manager.acknowledge_terminal_commit(successful=False)

    assert published_statuses == []
    assert manager.successful() is False
