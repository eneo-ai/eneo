"""Release the search data that replaced knowledge versions still hold.

Only the active version of a knowledge source is searched. Since 2.2 a replaced
version kept its chunks and vectors anyway, so they counted toward the storage
quota and grew the database. Publication now releases them when it replaces a
version; this command releases what earlier releases left behind, once after
the upgrade. Text, metadata, originals and citations of replaced versions stay.

Run inside the worker environment, at a quiet time:
    python -m eneo.info_blobs.replaced_versions status   # read only
    python -m eneo.info_blobs.replaced_versions run

Both commands walk all versions in id order, a page of rows at a time, each
page in its own short transaction. Progress goes to stderr, one JSON result to stdout. `run`
can be stopped (Ctrl-C or SIGTERM) and run again at any time.

Exit codes: 0 the walk reached the end; 2 `run` skipped versions other
transactions held, run it again; 3 the command stopped before the end.
"""

import argparse
import asyncio
import json
import signal
import sys
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa

if TYPE_CHECKING:
    from eneo.database.database import DatabaseSessionManager
    from eneo.info_blobs.info_blob_repo import InfoBlobRepository

BATCH_SIZE = 100
SCAN_PAGE_SIZE = 1000
PAUSE_SECONDS = 0.2


@dataclass(slots=True)
class CleanupProgress:
    """What committed batches have done. Only changes after a commit."""

    versions_read: int = 0
    released_versions: int = 0
    released_bytes: int = 0
    skipped_busy: int = 0
    last_confirmed_id: UUID | None = None
    pass_complete: bool = False


@dataclass(slots=True)
class StatusProgress:
    """Replaced versions seen holding chunks while walking all pages."""

    versions_read: int = 0
    remaining_observed: int = 0
    last_scanned_id: UUID | None = None
    pass_complete: bool = False


@asynccontextmanager
async def _bounded(
    database: "DatabaseSessionManager",
) -> AsyncGenerator["InfoBlobRepository"]:
    """A short transaction: no long lock waits or statements, no parallel query.

    Parallel query needs shared memory, which a container's default 64 MB
    /dev/shm may not have room for.
    """
    from eneo.info_blobs.info_blob_repo import InfoBlobRepository

    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
        await session.execute(sa.text("SET LOCAL max_parallel_workers_per_gather = 0"))
        yield InfoBlobRepository(session)


def _log(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=sys.stderr)


async def release_all(
    database: "DatabaseSessionManager",
    progress: CleanupProgress,
    *,
    limit: int = BATCH_SIZE,
    pause_seconds: float = PAUSE_SECONDS,
) -> CleanupProgress:
    """One pass over every replaced version, committing after each batch.

    `progress` is the caller's, so it still holds the committed work when a
    later batch raises.
    """
    while True:
        async with _bounded(database) as repo:
            batch = await repo.release_next_replaced_batch(
                after=progress.last_confirmed_id, limit=limit
            )
        if batch.last_scanned_id is None:
            progress.pass_complete = True
            return progress
        progress.versions_read += batch.versions_read
        progress.released_versions += batch.released_versions
        progress.released_bytes += batch.released_bytes
        progress.skipped_busy += batch.skipped_busy
        progress.last_confirmed_id = batch.last_scanned_id
        _log(
            f"read {progress.versions_read} replaced versions, "
            f"released {progress.released_versions} "
            f"({progress.released_bytes / 1e9:.2f} GB), "
            f"skipped {progress.skipped_busy} busy, "
            f"through {progress.last_confirmed_id}"
        )
        # Pause in proportion to what was released: a full page of releases
        # waits `pause_seconds`, a page with nothing to release does not wait.
        if batch.released_versions:
            await asyncio.sleep(pause_seconds * batch.released_versions / limit)


async def scan_remaining(
    database: "DatabaseSessionManager",
    progress: StatusProgress,
    *,
    limit: int = SCAN_PAGE_SIZE,
) -> StatusProgress:
    """Walk all versions and count the replaced ones that still hold chunks.

    Read-only. The pages are separate transactions, so the count is what the
    walk observed, not a snapshot.
    """
    while True:
        async with _bounded(database) as repo:
            page = await repo.scan_replaced_page(
                after=progress.last_scanned_id, limit=limit
            )
        if page.last_id is None:
            progress.pass_complete = True
            return progress
        progress.versions_read += page.versions_read
        progress.remaining_observed += len(page.with_search_data)
        progress.last_scanned_id = page.last_id
        _log(
            f"read {progress.versions_read} replaced versions, "
            f"{progress.remaining_observed} hold search data, "
            f"through {progress.last_scanned_id}"
        )


def _as_json(progress: CleanupProgress | StatusProgress) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in asdict(progress).items()
    }


async def _execute(
    command: str, database: "DatabaseSessionManager"
) -> tuple[dict[str, Any], int]:
    # Cancellation is how Ctrl-C and SIGTERM arrive; it reports like a failure.
    if command == "status":
        status = StatusProgress()
        try:
            await scan_remaining(database, status, limit=SCAN_PAGE_SIZE)
        except (Exception, asyncio.CancelledError):
            traceback.print_exc()
            return {
                **_as_json(status),
                "outcome": "inconclusive",
                "detail": "The walk stopped before the end, so nothing is known about the versions after last_scanned_id. The cause is above. Run status again.",
            }, 3
        return {
            **_as_json(status),
            "detail": "Every replaced version was read once. None holds search data."
            if status.remaining_observed == 0
            else "Replaced versions still hold search data. Release it with run.",
        }, 0

    progress = CleanupProgress()
    try:
        await release_all(
            database, progress, limit=BATCH_SIZE, pause_seconds=PAUSE_SECONDS
        )
    except (Exception, asyncio.CancelledError):
        traceback.print_exc()
        return {
            **_as_json(progress),
            "outcome": "incomplete",
            "detail": "The pass stopped before the end. The numbers count committed batches; the batch that was running may or may not have committed. The cause is above. Running again is safe.",
        }, 3
    if progress.skipped_busy:
        return {
            **_as_json(progress),
            "detail": "The pass finished, but skipped versions other transactions held, for example a running crawl. Run again.",
        }, 2
    return {
        **_as_json(progress),
        "detail": "The pass finished. Every replaced version it read has released its search data.",
    }, 0


async def _run(command: str) -> tuple[dict[str, Any], int]:
    from eneo.database.database import DatabaseSessionManager
    from eneo.main.config import get_settings

    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    database = DatabaseSessionManager()
    database.init(get_settings().database_url)
    # asyncio.run turns Ctrl-C into cancellation; do the same for `kill`, so a
    # stopped run still prints what it committed.
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        return await _execute(command, database)
    finally:
        try:
            await database.close()
        except (Exception, asyncio.CancelledError):
            # The result above is already decided; neither a failure nor a
            # stop while closing can change it.
            traceback.print_exc()
        loop.remove_signal_handler(signal.SIGTERM)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("status", "run"))
    arguments = parser.parse_args()
    # App loggers bind their console stream on import. Keep diagnostics on
    # stderr and reserve stdout for one complete JSON result.
    with redirect_stdout(sys.stderr):
        try:
            result, exit_code = asyncio.run(_run(arguments.command))
        except Exception:
            # Reached only when the command could not start, for example
            # without a database connection: nothing has been changed.
            traceback.print_exc()
            result = {
                "outcome": "not_started",
                "detail": "The command could not start. The cause is above.",
            }
            exit_code = 3
    print(json.dumps(result, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
