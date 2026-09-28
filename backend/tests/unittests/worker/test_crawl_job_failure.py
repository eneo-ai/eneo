"""A crawl that fails before producing results is recorded as failed on the
job immediately, with its reason, rather than being left for the watchdog."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from intric.main.models import Status
from intric.worker.crawl_tasks import _mark_job_failed
from intric.worker.task_manager import TaskManager


async def test_task_manager_keeps_the_failure_reason():
    manager = TaskManager(user=MagicMock(), job_id=uuid4())
    manager._publish_status = AsyncMock()

    async with manager.set_status_on_exception(status_already_set=True):
        raise RuntimeError("Crawl refused for http://x: not allowed")

    assert manager.successful() is False
    assert manager.error_message == "Crawl refused for http://x: not allowed"


async def test_mark_job_failed_writes_status_reason_and_finish_time():
    session = MagicMock()
    session.execute = AsyncMock()

    @asynccontextmanager
    async def scope():
        yield session

    job_id = uuid4()
    with patch("intric.main.container.container.Container.session_scope", scope):
        await _mark_job_failed(job_id, "Crawl refused for http://x: not allowed")

    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "UPDATE jobs" in sql
    assert f"'{Status.FAILED.value}'" in sql
    assert "finished_at" in sql
    assert "Crawl refused for http://x" in sql
    assert "'queued'" in sql and "'in progress'" in sql  # only still-running jobs


async def test_mark_job_failed_never_raises():
    @asynccontextmanager
    async def broken():
        raise ConnectionError("db down")
        yield  # pragma: no cover

    with patch("intric.main.container.container.Container.session_scope", broken):
        await _mark_job_failed(uuid4(), "x")
