"""Isolated reader for the PostgreSQL-inline streaming resource benchmark."""

import asyncio
import ctypes
import gc
import json
import os
import resource
import sys
import threading
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import configure_mappers

from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import ContentAccessClass, ContentReadGrant
from eneo.object_content.content_service import ObjectContentService


def resident_bytes() -> int:
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libproc.dylib")
        buffer = ctypes.create_string_buffer(128)
        size = library.proc_pidinfo(os.getpid(), 4, 0, buffer, len(buffer))
        if size < 16:
            raise RuntimeError("Could not read process resident memory")
        return int.from_bytes(buffer.raw[8:16], sys.byteorder)
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf(
        "SC_PAGE_SIZE"
    )


async def main() -> None:
    request = json.loads(sys.stdin.readline())
    configure_mappers()
    database = DatabaseSessionManager()
    database.init(request["database_url"])
    settings = ObjectContentCoreSettings(_env_file=None)
    service = ObjectContentService(settings, database)
    grant = ContentReadGrant(
        UUID(request["content_id"]),
        UUID(request["tenant_id"]),
        ContentAccessClass.PRIVATE_RESOURCE,
    )
    concurrency = request["concurrency"]
    warm = asyncio.Barrier(concurrency)

    async def warm_connection():
        async with database.session() as session, session.begin():
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            await warm.wait()
            return pid

    pids = await asyncio.gather(*(warm_connection() for _ in range(concurrency)))
    gc.collect()
    baseline = resident_bytes()
    peak = baseline
    stop = threading.Event()

    def sample():
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, resident_bytes())
            stop.wait(0.002)

    counters = {"slice_queries": 0, "sql_statements": 0, "transaction_boundaries": 0}

    def executed(connection, cursor, statement, parameters, context, executemany):
        counters["sql_statements"] += 1
        if "substr(" in statement:
            counters["slice_queries"] += 1

    def boundary(connection):
        counters["transaction_boundaries"] += 1

    engine = database._engine
    assert engine is not None
    event.listen(engine.sync_engine, "after_cursor_execute", executed)
    event.listen(engine.sync_engine, "begin", boundary)
    event.listen(engine.sync_engine, "rollback", boundary)
    print(
        "READER_READY "
        + json.dumps(
            {
                "pids": pids,
                "baseline_rss_bytes": baseline,
                "pool_capacity": engine.pool.size(),
                "pool_overflow": engine.pool._max_overflow,
            }
        ),
        flush=True,
    )
    await asyncio.to_thread(sys.stdin.readline)
    sampler = threading.Thread(target=sample)
    sampler.start()

    async def read():
        digest = sha256()
        length = 0
        started = perf_counter()
        async with service.open_content(
            grant, require_local_path=request["local_path"]
        ) as opened:
            if request["local_path"]:
                assert opened.verified_path is not None
                with opened.verified_path.open("rb") as file:
                    while chunk := await asyncio.to_thread(
                        file.read, settings.inline_io_chunk_bytes
                    ):
                        digest.update(chunk)
                        length += len(chunk)
            else:
                async for chunk in opened.chunks:
                    digest.update(chunk)
                    length += len(chunk)
        assert digest.hexdigest() == request["sha256"]
        assert length == request["size_bytes"]
        return perf_counter() - started

    try:
        latencies = await asyncio.gather(*(read() for _ in range(concurrency)))
    finally:
        stop.set()
        sampler.join()
    assert engine.pool.checkedout() == 0
    print(
        "READER_RESULT "
        + json.dumps(
            {
                **counters,
                "total_statements": counters["sql_statements"]
                + counters["transaction_boundaries"],
                "latencies_seconds": latencies,
                "peak_rss_bytes": peak,
                "rss_delta_bytes": peak - baseline,
                "process_high_water_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * (1 if sys.platform == "darwin" else 1024),
            }
        ),
        flush=True,
    )
    await asyncio.to_thread(sys.stdin.readline)
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
