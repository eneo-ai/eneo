"""The stale-job reaper never waits for a job row a running task holds."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_models import Task
from eneo.jobs.job_repo import JobRepository
from eneo.main.models import Status

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SYNC_TASKS = [Task.PULL_SHAREPOINT_CONTENT.value, Task.SYNC_SHAREPOINT_DELTA.value]


async def test_a_locked_stale_job_is_skipped_and_an_unlocked_one_reaped(
    db_container, admin_user
):
    long_ago = datetime.now(timezone.utc) - timedelta(hours=5)
    running, crashed = uuid4(), uuid4()
    async with db_container(user=admin_user) as container:
        container.session().add_all(
            [
                Jobs(
                    id=job_id,
                    user_id=admin_user.id,
                    name="Library",
                    task=Task.SYNC_SHAREPOINT_DELTA.value,
                    status=Status.QUEUED.value,
                    updated_at=long_ago,
                )
                for job_id in (running, crashed)
            ]
        )

    async with sessionmanager.session() as sync_session, sync_session.begin():
        # The running sync's own write, uncommitted for the rest of its run.
        await sync_session.execute(
            sa.update(Jobs)
            .where(Jobs.id == running)
            .values(status=Status.IN_PROGRESS.value)
        )
        async with sessionmanager.session() as reaper_session, reaper_session.begin():
            failed = await asyncio.wait_for(
                JobRepository(reaper_session).mark_stale_jobs_failed(
                    tasks=SYNC_TASKS,
                    stale_before=datetime.now(timezone.utc) - timedelta(hours=2),
                ),
                timeout=10,
            )

    assert failed == [crashed]
    async with db_container(user=admin_user) as container:
        statuses = dict(
            (
                await container.session().execute(
                    sa.select(Jobs.id, Jobs.status).where(
                        Jobs.id.in_([running, crashed])
                    )
                )
            ).all()
        )
    assert statuses == {
        running: Status.IN_PROGRESS.value,
        crashed: Status.FAILED.value,
    }
