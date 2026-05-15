from typing import cast
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from intric.main.models import Status
from intric.worker.crawl.preemption import is_job_preempted


class _ScalarResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _RecordingSession:
    def __init__(self, value: str | None) -> None:
        self._value = value
        self.statements: list[sa.sql.ClauseElement] = []

    async def execute(self, statement: sa.sql.ClauseElement) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult(self._value)


def _compile(statement: sa.sql.ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


async def test_is_job_preempted_returns_true_when_job_was_marked_failed() -> None:
    session = _RecordingSession(Status.FAILED.value)

    preempted = await is_job_preempted(
        cast(AsyncSession, session),
        job_id=uuid4(),
    )

    assert preempted is True


async def test_is_job_preempted_returns_false_for_active_or_missing_jobs() -> None:
    active_session = _RecordingSession(Status.IN_PROGRESS.value)
    missing_session = _RecordingSession(None)

    assert (
        await is_job_preempted(cast(AsyncSession, active_session), job_id=uuid4())
        is False
    )
    assert (
        await is_job_preempted(cast(AsyncSession, missing_session), job_id=uuid4())
        is False
    )


async def test_is_job_preempted_queries_the_requested_job_status() -> None:
    job_id = uuid4()
    session = _RecordingSession(Status.COMPLETE.value)

    await is_job_preempted(cast(AsyncSession, session), job_id=job_id)

    assert len(session.statements) == 1
    compiled_sql = _compile(session.statements[0])
    assert "SELECT jobs.status" in compiled_sql
    assert f"jobs.id = '{job_id}'" in compiled_sql
