"""Release the search data that replaced knowledge versions still hold.

Only the active version of a knowledge source is searched. Since 2.2 a replaced
version kept its chunks and vectors anyway, so they counted toward the storage
quota and grew the database. Publication now releases them when it replaces a
version; this command releases what earlier releases left behind. Text,
metadata, originals and citations of replaced versions stay.

Run inside the worker environment, at a quiet time:
    python -m eneo.info_blobs.replaced_versions status|run

`run` works in small transactions and can be stopped and rerun at any time.
"""

import argparse
import asyncio
import json
import sys
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

if TYPE_CHECKING:
    from eneo.database.database import DatabaseSessionManager
    from eneo.info_blobs.info_blob_repo import InfoBlobRepository

BATCH_SIZE = 100
PAUSE_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class CleanupResult:
    released_versions: int
    released_bytes: int
    skipped_busy: int
    remaining: int


@asynccontextmanager
async def _bounded(
    database: "DatabaseSessionManager",
) -> AsyncGenerator["InfoBlobRepository"]:
    """A transaction that never waits long on a lock or runs unbounded."""
    from eneo.info_blobs.info_blob_repo import InfoBlobRepository

    async with database.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(sa.text("SET LOCAL statement_timeout = '60s'"))
        yield InfoBlobRepository(session)


async def count_remaining(database: "DatabaseSessionManager") -> int:
    async with _bounded(database) as repo:
        return await repo.count_replaced_with_search_data()


async def release_all(
    database: "DatabaseSessionManager",
    *,
    limit: int = BATCH_SIZE,
    pause_seconds: float = PAUSE_SECONDS,
) -> CleanupResult:
    """One pass over every replaced version, committing after each batch."""
    released_versions = released_bytes = skipped_busy = 0
    after: UUID | None = None
    while True:
        async with _bounded(database) as repo:
            batch = await repo.release_next_replaced_batch(after=after, limit=limit)
        if batch.last_scanned_id is None:
            break
        released_versions += batch.released_versions
        released_bytes += batch.released_bytes
        skipped_busy += batch.skipped_busy
        after = batch.last_scanned_id
        print(
            f"Released {released_versions} replaced versions "
            f"({released_bytes} bytes) so far",
            file=sys.stderr,
        )
        await asyncio.sleep(pause_seconds)
    remaining = await count_remaining(database)
    return CleanupResult(released_versions, released_bytes, skipped_busy, remaining)


async def _run(command: str) -> tuple[str, int]:
    from eneo.database.database import DatabaseSessionManager
    from eneo.main.config import get_settings

    database = DatabaseSessionManager()
    database.init(get_settings().database_url)
    try:
        if command == "status":
            remaining = await count_remaining(database)
            return json.dumps({"remaining": remaining}, indent=2), 0
        result = await release_all(database)
        detail = (
            "Every replaced version has released its search data"
            if result.remaining == 0
            else "Some replaced versions were busy or changed during the pass; run again"
        )
        return (
            json.dumps({**asdict(result), "detail": detail}, indent=2),
            0 if result.remaining == 0 else 2,
        )
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "run"))
    arguments = parser.parse_args()
    # App loggers bind their console stream on import. Keep diagnostics on
    # stderr and reserve stdout for one complete JSON result.
    with redirect_stdout(sys.stderr):
        try:
            result, exit_code = asyncio.run(_run(arguments.command))
        except Exception:
            # CLI boundary: committed batches stay committed, so the operator
            # can check status and run again.
            traceback.print_exc()
            result = json.dumps(
                {
                    "outcome": "incomplete",
                    "detail": "The command stopped early. Released batches are kept; check database connectivity and locks, then run status and run again.",
                },
                indent=2,
            )
            exit_code = 3
    print(result)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
