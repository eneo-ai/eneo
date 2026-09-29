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

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.file_icon_backfill import (
    FileIconBackfill,
    FileIconBackfillSettings,
    FileIconBackfillState,
)


def _peak_rss_bytes() -> int:
    if sys.platform == "linux":
        # Linux preserves ru_maxrss across execve, including the pytest parent's
        # peak. VmHWM belongs to this worker's new address space after execve.
        for line in Path("/proc/self/status").read_text().splitlines():
            fields = line.split()
            if fields and fields[0] == "VmHWM:":
                if len(fields) != 3 or fields[2] != "kB":
                    raise ValueError(f"Unexpected VmHWM format: {line}")
                return int(fields[1]) * 1024
        raise RuntimeError("VmHWM is missing from /proc/self/status")

    units = 1 if sys.platform == "darwin" else 1024
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * units)


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
                    "rss_after_init_bytes": rss_after_init,
                    "rss_after_first_run_bytes": rss_after_first_run,
                    "max_rss_bytes": _peak_rss_bytes(),
                    "rss_measurement": (
                        "procfs_vmhwm" if sys.platform == "linux" else "getrusage"
                    ),
                    "cpu_seconds": usage.ru_utime + usage.ru_stime,
                }
            )
        )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(_worker_main())
