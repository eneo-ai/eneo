from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.jobs.job_repo import JobRepository


@pytest.mark.asyncio
async def test_mark_stale_jobs_failed_targets_queued_and_in_progress():
    """The reaper must cover QUEUED too: a hard crash rolls the sync transaction
    back to QUEUED, so an IN_PROGRESS-only filter would never find stuck jobs."""
    captured: dict[str, object] = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        result = MagicMock()
        result.all.return_value = []
        return result

    session = AsyncMock()
    session.execute = fake_execute

    repo = JobRepository(session=session)
    await repo.mark_stale_jobs_failed(
        tasks=["pull_sharepoint_content", "sync_sharepoint_delta"],
        stale_before=datetime.now(timezone.utc),
    )

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "in progress" in sql
    assert "queued" in sql
    assert "failed" in sql  # sets status to FAILED
