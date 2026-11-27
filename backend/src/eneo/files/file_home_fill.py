"""Give the files from before homes existed their home space.

A file belongs in one space, its home. New files get theirs when they are
created or attached. Files from earlier releases have none; this command
fills it in, once after the upgrade.

For each space, a file family that is used in that space and nowhere else
gets the space as its home. A family that is used in several spaces, or
whose use leads to no space, cannot be placed: it keeps working as before,
stays without a home, and is listed as unresolved for an administrator to
decide about. Uploads that are not used anywhere (drafts) are left alone.
No id changes and nothing is split or copied.

Run inside the worker environment, at a quiet time:
    python -m eneo.files.file_home_fill status   # read only
    python -m eneo.files.file_home_fill run

`run` walks the spaces in id order and fills in a batch of files at a time,
each batch in its own short transaction. Progress goes to stderr, one JSON
result to stdout. It can be stopped (Ctrl-C or SIGTERM) and run again at any
time: a file that has its home is not looked at again.

Exit codes: 0 the walk reached the end; 3 the command stopped before the end.
"""

import argparse
import asyncio
import json
import signal
import sys
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import aliased

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.database.database import DatabaseSessionManager

BATCH_SIZE = 200
SPACE_PAGE_SIZE = 500
PAUSE_SECONDS = 0.1
# The result lists the unresolved files so that someone can act on them, but a
# result of unbounded size helps nobody: beyond this the count is what is told.
UNRESOLVED_LISTED = 5000


@dataclass(slots=True)
class FillProgress:
    """What committed batches have done. Only changes after a commit."""

    spaces_done: int = 0
    placed: int = 0
    # Root file id -> why its family could not be placed.
    unresolved: dict[UUID, str] = field(default_factory=dict[UUID, str])
    unresolved_total: int = 0
    last_space_id: UUID | None = None
    pass_complete: bool = False


@dataclass(slots=True)
class FillStatus:
    """What is left to fill in, read once."""

    files_with_home: int = 0
    in_use_without_home: int = 0
    drafts: int = 0


@asynccontextmanager
async def _bounded(
    database: "DatabaseSessionManager",
) -> AsyncGenerator["AsyncSession"]:
    """A short transaction: no long lock waits or statements."""
    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
        await session.execute(sa.text("SET LOCAL max_parallel_workers_per_gather = 0"))
        yield session


def _log(message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=sys.stderr)


async def fill_all(
    database: "DatabaseSessionManager",
    progress: FillProgress,
    *,
    limit: int = BATCH_SIZE,
    pause_seconds: float = PAUSE_SECONDS,
) -> FillProgress:
    """One pass over every space, committing after each batch of files.

    `progress` is the caller's, so it still holds the committed work when a
    later batch raises.
    """
    from eneo.database.tables.spaces_table import Spaces
    from eneo.files.file_home import FileHomes

    while True:
        async with _bounded(database) as session:
            page = sa.select(Spaces.id).order_by(Spaces.id).limit(SPACE_PAGE_SIZE)
            if progress.last_space_id is not None:
                page = page.where(Spaces.id > progress.last_space_id)
            space_ids = (await session.scalars(page)).all()
        if not space_ids:
            progress.pass_complete = True
            return progress
        for space_id in space_ids:
            after: UUID | None = None
            while True:
                async with _bounded(database) as session:
                    batch = await FileHomes(session).fill_in_space(
                        space_id, after=after, limit=limit
                    )
                progress.placed += batch.placed
                for root_id, reason in batch.unresolved.items():
                    if root_id in progress.unresolved:
                        continue
                    progress.unresolved_total += 1
                    if len(progress.unresolved) < UNRESOLVED_LISTED:
                        progress.unresolved[root_id] = reason.value
                after = batch.next_after
                if batch.placed:
                    await asyncio.sleep(pause_seconds)
                if after is None:
                    break
            progress.spaces_done += 1
            progress.last_space_id = space_id
        _log(
            f"filled in {progress.spaces_done} spaces: "
            f"{progress.placed} file families placed, "
            f"{progress.unresolved_total} unresolved, "
            f"through space {progress.last_space_id}"
        )


async def read_status(database: "DatabaseSessionManager") -> FillStatus:
    """Count what has a home, what is in use without one, and the drafts.

    Read-only. The counts are separate statements, so they are what each one
    observed, not a snapshot.
    """
    from eneo.database.tables.files_table import Files
    from eneo.files.file_usage import FILE_USAGE_COLUMNS

    in_use = sa.or_(
        *(sa.exists().where(column == Files.id) for _, column in FILE_USAGE_COLUMNS)
    )
    status = FillStatus()
    async with _bounded(database) as session:
        status.files_with_home = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(Files.home_space_id.is_not(None))
            )
            or 0
        )
    async with _bounded(database) as session:
        status.in_use_without_home = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(Files.home_space_id.is_(None), in_use)
            )
            or 0
        )
    async with _bounded(database) as session:
        derived = aliased(Files)
        derived_in_use = sa.exists().where(
            derived.parent_file_id == Files.id,
            sa.or_(
                *(
                    sa.exists().where(column == derived.id)
                    for _, column in FILE_USAGE_COLUMNS
                )
            ),
        )
        status.drafts = int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(
                    Files.home_space_id.is_(None),
                    Files.parent_file_id.is_(None),
                    sa.not_(in_use),
                    sa.not_(derived_in_use),
                )
            )
            or 0
        )
    return status


def _progress_json(progress: FillProgress) -> dict[str, Any]:
    return {
        "spaces_done": progress.spaces_done,
        "placed": progress.placed,
        "unresolved_total": progress.unresolved_total,
        "unresolved": {
            str(root): reason for root, reason in progress.unresolved.items()
        },
        "unresolved_listed": len(progress.unresolved),
        "last_space_id": str(progress.last_space_id)
        if progress.last_space_id
        else None,
        "pass_complete": progress.pass_complete,
    }


async def _execute(
    command: str, database: "DatabaseSessionManager"
) -> tuple[dict[str, Any], int]:
    # Cancellation is how Ctrl-C and SIGTERM arrive; it reports like a failure.
    if command == "status":
        try:
            status = await read_status(database)
        except (Exception, asyncio.CancelledError):
            traceback.print_exc()
            return {
                "outcome": "inconclusive",
                "detail": "The counts could not be read. The cause is above. Run status again.",
            }, 3
        return {
            "files_with_home": status.files_with_home,
            "in_use_without_home": status.in_use_without_home,
            "drafts": status.drafts,
            "detail": "Every file that is in use has a home."
            if status.in_use_without_home == 0
            else "Files are in use without a home. Fill them in with run; the ones that remain after it are unresolved.",
        }, 0

    progress = FillProgress()
    try:
        await fill_all(database, progress)
    except (Exception, asyncio.CancelledError):
        traceback.print_exc()
        return {
            **_progress_json(progress),
            "outcome": "incomplete",
            "detail": "The pass stopped before the end. The numbers count committed batches; the batch that was running may or may not have committed. The cause is above. Running again is safe.",
        }, 3
    return {
        **_progress_json(progress),
        "detail": "The pass finished. Every file family used in one space only has that space as its home."
        if progress.unresolved_total == 0
        else "The pass finished. The unresolved file families are used in several spaces, or their use leads to no space; they keep working and have no home.",
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
