"""Run the frozen slice-2 measurements with ENEO_RUN_INLINE_READ_BENCHMARK=1."""

import asyncio
import gc
import json
import math
import os
import sys
from hashlib import sha256
from random import Random

import pytest
from sqlalchemy import text

from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.reconciliation import ObjectContentReconciler
from tests.integration.object_content.test_inline_external_storage import _upload
from tests.integration.object_content.test_storage_ownership import _owner_ids

pytestmark = pytest.mark.skipif(
    os.environ.get("ENEO_RUN_INLINE_READ_BENCHMARK") != "1",
    reason="Explicit PostgreSQL-inline resource benchmark",
)


def _backend_memory(container, pids):
    result = {}
    for pid in pids:
        code, output = container.get_wrapped_container().exec_run(
            ["cat", f"/proc/{pid}/status"]
        )
        assert code == 0
        values = {}
        for line in output.decode().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                name, value, _ = line.split()
                values[name[:-1]] = int(value) * 1024
        result[pid] = values
    return result


async def _reader(
    database, container, *, content_id, tenant_id, size, digest, local_path, concurrency
):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.integration.object_content.inline_streaming_reader",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    stderr = asyncio.create_task(process.stderr.read())
    request = {
        "database_url": database._engine.url.render_as_string(hide_password=False),
        "content_id": str(content_id),
        "tenant_id": str(tenant_id),
        "sha256": digest,
        "size_bytes": size,
        "local_path": local_path,
        "concurrency": concurrency,
    }
    process.stdin.write((json.dumps(request) + "\n").encode())
    await process.stdin.drain()

    async def receive(marker):
        while line := await process.stdout.readline():
            if line.startswith(marker.encode()):
                return json.loads(line[len(marker) :])
        raise AssertionError((await stderr).decode())

    try:
        ready = await asyncio.wait_for(receive("READER_READY "), 180)
        before = await asyncio.to_thread(_backend_memory, container, ready["pids"])
        process.stdin.write(b"go\n")
        await process.stdin.drain()
        lock_wait_observations = 0
        finished = asyncio.Event()

        async def monitor_locks():
            nonlocal lock_wait_observations
            async with database.session() as observer, observer.begin():
                while not finished.is_set():
                    lock_wait_observations += await observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"
                        ),
                        {"pids": ready["pids"]},
                    )
                    await asyncio.sleep(0.01)

        monitor = asyncio.create_task(monitor_locks())
        try:
            result = await asyncio.wait_for(receive("READER_RESULT "), 180)
        finally:
            finished.set()
            await monitor
        result["lock_wait_observations"] = lock_wait_observations
        after = await asyncio.to_thread(_backend_memory, container, ready["pids"])
        process.stdin.write(b"close\n")
        await process.stdin.drain()
        assert await asyncio.wait_for(process.wait(), 20) == 0, (await stderr).decode()
        return {
            **ready,
            **result,
            "backend_memory_before": before,
            "backend_memory_after": after,
        }
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await stderr


async def _postgres_work(database, content_id, size, chunk):
    execution_ms = 0.0
    blocks = 0
    async with database.session() as session, session.begin():
        for offset in range(0, size, chunk):
            plan = (
                await session.scalar(
                    text(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                        "SELECT substr(payload, :start, :length) FROM inline_content_payloads WHERE content_id = :id"
                    ),
                    {
                        "id": content_id,
                        "start": offset + 1,
                        "length": min(chunk, size - offset),
                    },
                )
            )[0]
            execution_ms += plan["Execution Time"]
            blocks += (
                plan["Plan"]["Shared Hit Blocks"] + plan["Plan"]["Shared Read Blocks"]
            )
        exceptional = (
            await session.scalar(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT sha256(payload) "
                    "FROM inline_content_payloads WHERE content_id = :id"
                ),
                {"id": content_id},
            )
        )[0]
    return {
        "slice_execution_ms": execution_ms,
        "slice_buffer_accesses": blocks,
        "exceptional_fence_hash_execution_ms": exceptional["Execution Time"],
        "exceptional_fence_hash_buffer_accesses": exceptional["Plan"][
            "Shared Hit Blocks"
        ]
        + exceptional["Plan"]["Shared Read Blocks"],
    }


async def test_frozen_inline_read_resource_gate(
    object_content_database, object_content_postgres_13
):
    database = object_content_database
    settings = ObjectContentCoreSettings(_env_file=None)
    tenant_id, _ = await _owner_ids(database)
    memory_measurements = []
    for mib in (16, 384, 64):
        size = mib * 1024 * 1024
        random = Random(42)
        fixture_block_bytes = 4 * 1024 * 1024
        payload = b"".join(
            random.randbytes(min(fixture_block_bytes, size - offset))
            for offset in range(0, size, fixture_block_bytes)
        )
        digest = sha256(payload).hexdigest()
        content_id = await _upload(database, payload)
        del payload
        gc.collect()
        await ObjectContentReconciler(settings, database).run_once()
        work = await _postgres_work(
            database, content_id, size, settings.inline_io_chunk_bytes
        )
        print("POSTGRES_WORK " + json.dumps({"mib": mib, **work}), flush=True)
        for local_path in (False, True):
            single = await _reader(
                database,
                object_content_postgres_13,
                content_id=content_id,
                tenant_id=tenant_id,
                size=size,
                digest=digest,
                local_path=local_path,
                concurrency=1,
            )
            print(
                "INLINE_READ "
                + json.dumps(
                    {"mib": mib, "local_path": local_path, "concurrency": 1, **single}
                ),
                flush=True,
            )
            assert single["lock_wait_observations"] == 0
            assert single["slice_queries"] == math.ceil(
                size / settings.inline_io_chunk_bytes
            )
            memory_measurements.append((mib, local_path, 1, single["rss_delta_bytes"]))
            if mib == 384:
                assert single["latencies_seconds"][0] < 60
            if mib == 64:
                assert single["latencies_seconds"][0] < 2
                concurrent = await _reader(
                    database,
                    object_content_postgres_13,
                    content_id=content_id,
                    tenant_id=tenant_id,
                    size=size,
                    digest=digest,
                    local_path=local_path,
                    concurrency=4,
                )
                p95 = max(concurrent["latencies_seconds"])
                ratio = p95 / single["latencies_seconds"][0]
                print(
                    "INLINE_READ "
                    + json.dumps(
                        {
                            "mib": mib,
                            "local_path": local_path,
                            "concurrency": 4,
                            "p95_seconds": p95,
                            "latency_ratio": ratio,
                            **concurrent,
                        }
                    ),
                    flush=True,
                )
                assert concurrent["lock_wait_observations"] == 0
                assert concurrent["slice_queries"] == 4 * math.ceil(
                    size / settings.inline_io_chunk_bytes
                )
                memory_measurements.append(
                    (mib, local_path, 4, concurrent["rss_delta_bytes"])
                )
                assert p95 < 5, (
                    "Frozen concurrent-read latency threshold failed; stop this slice"
                )
    memory_limits = {1: 16 * 1024 * 1024, 4: 32 * 1024 * 1024}
    memory_failures = [
        {
            "mib": mib,
            "local_path": local_path,
            "concurrency": concurrency,
            "rss_delta_bytes": delta,
            "limit_bytes": memory_limits[concurrency],
        }
        for mib, local_path, concurrency, delta in memory_measurements
        if delta >= memory_limits[concurrency]
    ]
    assert not memory_failures, memory_failures
    single_memory = {
        (mib, local_path): delta
        for mib, local_path, concurrency, delta in memory_measurements
        if concurrency == 1
    }
    for local_path in (False, True):
        assert (
            single_memory[384, local_path]
            < 2 * single_memory[16, local_path] + 4 * 1024 * 1024
        )
