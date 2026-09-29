"""Run only the File/Icon backfill in the rehearsal subprocess.

The parent integration test imports API and test infrastructure that the
backfill does not need. Keeping this entry point separate makes its RSS
measurement reflect the worker rather than that test harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import sys
import time
from pathlib import Path

_BYTES_PER_RUSAGE_UNIT = 1 if sys.platform == "darwin" else 1024


def _peak_rss_bytes() -> int:
    return int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _BYTES_PER_RUSAGE_UNIT
    )


_IMPORT_RSS_STAGES = {"stdlib": _peak_rss_bytes()}

from eneo.database.database import DatabaseSessionManager

_IMPORT_RSS_STAGES["database"] = _peak_rss_bytes()

from eneo.object_content.configuration import ObjectContentCoreSettings

_IMPORT_RSS_STAGES["configuration"] = _peak_rss_bytes()

from eneo.object_content.content_service import ObjectContentService

_IMPORT_RSS_STAGES["content_service"] = _peak_rss_bytes()

from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)

_IMPORT_RSS_STAGES["file_icon_backfill"] = _peak_rss_bytes()


async def _worker_main() -> None:
    rss_after_imports = _peak_rss_bytes()
    database = DatabaseSessionManager()
    database.init(os.environ["ENEO_REHEARSAL_CHILD_DATABASE"])
    worker = FileIconBackfill(
        FileIconBackfillSettings(
            batch_rows=32, lease_seconds=int(os.environ["ENEO_REHEARSAL_CHILD_LEASE"])
        ),
        ObjectContentService(ObjectContentCoreSettings(_env_file=None), database),
        database,
    )
    rss_after_init = _peak_rss_bytes()
    started = time.perf_counter()
    runs = 0
    active_seconds = 0.0
    rss_after_first_run: int | None = None
    try:
        async with asyncio.timeout(240):
            while True:
                batch_started = time.perf_counter()
                result = await worker.run_once()
                if rss_after_first_run is None:
                    rss_after_first_run = _peak_rss_bytes()
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
                    "rss_after_imports_bytes": rss_after_imports,
                    "rss_import_stages_bytes": _IMPORT_RSS_STAGES,
                    "rss_after_init_bytes": rss_after_init,
                    "rss_after_first_run_bytes": rss_after_first_run,
                    "max_rss_bytes": _peak_rss_bytes(),
                    "cpu_seconds": usage.ru_utime + usage.ru_stime,
                }
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(_worker_main())
