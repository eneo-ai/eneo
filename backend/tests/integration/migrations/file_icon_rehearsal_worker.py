"""The File/Icon backfill worker process for the bridge rehearsal.

Kept apart from the rehearsal test module, whose imports load the whole
application. The rehearsal's RSS ceiling is meant for the backfill worker,
not for every router and feature package the test itself needs.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import sys
import time
from pathlib import Path

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)


async def _worker_main():
    database = DatabaseSessionManager()
    database.init(os.environ["ENEO_REHEARSAL_CHILD_DATABASE"])
    worker = FileIconBackfill(
        FileIconBackfillSettings(
            batch_rows=32, lease_seconds=int(os.environ["ENEO_REHEARSAL_CHILD_LEASE"])
        ),
        ObjectContentService(ObjectContentCoreSettings(_env_file=None), database),
        database,
    )
    started = time.perf_counter()
    runs = 0
    active_seconds = 0.0
    try:
        async with asyncio.timeout(240):
            while True:
                batch_started = time.perf_counter()
                result = await worker.run_once()
                active_seconds += time.perf_counter() - batch_started
                runs += 1
                if result.state is FileIconBackfillState.COMPLETE:
                    break
                assert result.state is FileIconBackfillState.ACTIVE, result
                await asyncio.sleep(0.05)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        Path(os.environ["ENEO_REHEARSAL_CHILD_OUTPUT"]).write_text(
            json.dumps(
                {
                    "runs": runs,
                    "elapsed_seconds": time.perf_counter() - started,
                    "active_seconds": active_seconds,
                    "schedule": "repeated run_once with 50 ms gaps; production minute cron not exercised",
                    "max_rss_bytes": int(
                        usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                    ),
                    "cpu_seconds": usage.ru_utime + usage.ru_stime,
                    "application_loaded": "eneo.main.container.container"
                    in sys.modules,
                }
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(_worker_main())
