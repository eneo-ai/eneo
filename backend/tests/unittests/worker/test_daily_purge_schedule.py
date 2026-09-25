"""The daily purges the documentation promises are registered with the worker
at their times (UTC): the purge functions have their own tests, which pass
whether or not anything schedules them."""

import pytest

from eneo.worker.arq import WorkerSettings


@pytest.mark.parametrize(
    ("name", "hour", "minute"),
    [
        ("cron:purge_widget_sessions", 3, 30),
        ("cron:purge_oversight_visits", 3, 45),
    ],
)
def test_the_daily_purge_is_scheduled(name: str, hour: int, minute: int) -> None:
    jobs = {job.name: job for job in WorkerSettings.cron_jobs}
    assert name in jobs
    job = jobs[name]
    assert (job.hour, job.minute, job.second) == (hour, minute, 0)
    assert not job.run_at_startup
