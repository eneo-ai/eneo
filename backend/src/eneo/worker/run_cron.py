"""Enqueue a registered worker cron job on demand.

Cron jobs normally run on their ARQ schedule. When an operator needs one to
run now, for example to check the crawl scheduler after a deploy, this command
enqueues it on the queue of the worker that owns it, and that worker runs it
exactly as it would on schedule.

Run it inside a backend or worker container:

    run-cron --list
    run-cron crawl_all_websites
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from arq import create_pool
from arq.cron import CronJob

from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, DEFAULT_QUEUE_NAME
from eneo.redis.connection import build_arq_redis_settings

CRON_PREFIX = "cron:"


@dataclass(frozen=True)
class RegisteredCron:
    name: str
    """Short name as written in the worker module, e.g. ``crawl_all_websites``."""

    queue_name: str
    """ARQ queue consumed by the worker that registered the cron."""

    @property
    def job_name(self) -> str:
        """Function name ARQ registered the cron under."""
        return CRON_PREFIX + self.name


def registered_crons(
    cron_jobs_by_queue: Mapping[str, Iterable[CronJob]],
) -> list[RegisteredCron]:
    """Flatten per-queue cron registrations into one sorted list."""
    crons = [
        RegisteredCron(name=cron.name.removeprefix(CRON_PREFIX), queue_name=queue)
        for queue, cron_jobs in cron_jobs_by_queue.items()
        for cron in cron_jobs
    ]
    return sorted(crons, key=lambda cron: (cron.queue_name, cron.name))


def resolve_cron(requested: str, crons: Iterable[RegisteredCron]) -> RegisteredCron:
    """Find a cron by its short or ARQ name; raise LookupError when unknown."""
    short_name = requested.removeprefix(CRON_PREFIX)
    for cron in crons:
        if cron.name == short_name:
            return cron
    raise LookupError(
        f"Unknown cron job {requested!r}. Run with --list to see registered names."
    )


def _load_registry() -> list[RegisteredCron]:
    # Deferred: importing the worker module pulls in every task module.
    from eneo.worker.arq import crawler_worker, worker

    return registered_crons(
        {
            DEFAULT_QUEUE_NAME: worker.cron_jobs,
            CRAWLER_QUEUE_NAME: crawler_worker.cron_jobs,
        }
    )


async def enqueue_cron(cron: RegisteredCron) -> str:
    """Enqueue the cron on its worker's queue and return the ARQ job id."""
    redis = await create_pool(build_arq_redis_settings())
    try:
        job = await redis.enqueue_job(cron.job_name, _queue_name=cron.queue_name)
    finally:
        await redis.aclose()
    if job is None:
        raise RuntimeError(f"ARQ refused to enqueue {cron.job_name}")
    return job.job_id


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run-cron",
        description="Run a registered worker cron job now instead of on schedule.",
    )
    parser.add_argument(
        "name", nargs="?", help="cron job name, e.g. crawl_all_websites"
    )
    parser.add_argument(
        "--list", action="store_true", help="list registered cron jobs and exit"
    )
    args = parser.parse_args(argv)

    crons = _load_registry()
    if args.list:
        for cron in crons:
            print(f"{cron.name:<45} {cron.queue_name}")
        return 0
    if args.name is None:
        parser.error("a cron job name is required (or use --list)")

    try:
        cron = resolve_cron(args.name, crons)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 2

    job_id = asyncio.run(enqueue_cron(cron))
    print(
        f"Enqueued {cron.job_name} on queue {cron.queue_name} as job {job_id}. "
        "Follow the worker log for its output."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
