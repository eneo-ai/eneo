"""Opt-in measurement of the real admin endpoint against disposable PostgreSQL.

ENEO_RUN_CRAWLER_OVERVIEW_BENCHMARK=1 uv run pytest -s -m integration \
    tests/integration/test_admin_crawler_benchmark.py

Seeds 100,000 old runs and grows active runs from 100 to 10,000. HTTP samples
exclude setup and allocation tracing; query plans and memory are separate probes.
"""

import asyncio
import gc
import importlib.metadata
import json
import os
import platform
import resource
import statistics
import sys
import sysconfig
import time
import tracemalloc

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

pytest_plugins = ["tests.integration.test_website_latest_crawl"]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("ENEO_RUN_CRAWLER_OVERVIEW_BENCHMARK") != "1",
        reason="Opt-in crawler overview load measurement",
    ),
]


async def test_admin_crawler_scaling(
    client, db_container, admin_user, website_id, headers
):
    print(
        "CRAWLER_RUNTIME "
        + json.dumps(
            {
                "python": sys.version,
                "build": {
                    key: sysconfig.get_config_var(key)
                    for key in ("Py_DEBUG", "Py_GIL_DISABLED", "CONFIG_ARGS")
                },
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "gil": getattr(sys, "_is_gil_enabled", lambda: True)(),
                "jit_enabled": getattr(
                    getattr(sys, "_jit", None), "is_enabled", lambda: False
                )(),
                "allocator": os.getenv("PYTHONMALLOC", "default"),
                "available_cpus": os.cpu_count(),
                "gc": gc.get_threshold(),
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("sqlalchemy", "asyncpg", "fastapi", "pydantic")
                },
                "http_processes": 1,
                "database": "PostgreSQL 16 testcontainers; warm cache",
            }
        )
    )
    async with db_container(user=admin_user) as container:
        await container.session().execute(
            sa.text("""
            INSERT INTO crawl_runs (website_id, tenant_id, phase, outcome, origin, finished_at)
            SELECT :website, :tenant, 'terminal', 'succeeded', 'legacy', now() - interval '2 days'
            FROM generate_series(1, 100000)
        """),
            {"website": website_id, "tenant": admin_user.tenant_id},
        )
    previous = 0
    for size in (100, 1000, 10000):
        async with db_container(user=admin_user) as container:
            session = container.session()
            await session.execute(
                sa.text("""
                CREATE TEMP TABLE overview_seed ON COMMIT DROP AS
                SELECT gen_random_uuid() AS website_id, gen_random_uuid() AS run_id,
                       n, CASE WHEN n % 2 = 0 THEN 'running' ELSE 'queued' END AS phase
                FROM generate_series(CAST(:first AS integer), CAST(:last AS integer)) AS n
            """),
                {"first": previous + 1, "last": size},
            )
            await session.execute(
                sa.text("""
                INSERT INTO websites (id, name, url, download_files, crawl_type,
                    update_interval, size, tenant_id, user_id, embedding_model_id, space_id)
                SELECT s.website_id, CASE WHEN s.n % 4 = 0 THEN NULL ELSE 'Source ' || s.n END,
                    'https://benchmark-source-' || s.n || '.example.test', false, w.crawl_type,
                    'never', 0, w.tenant_id, w.user_id, w.embedding_model_id, w.space_id
                FROM overview_seed s CROSS JOIN websites w WHERE w.id = :website
            """),
                {"website": website_id},
            )
            await session.execute(
                sa.text("""
                INSERT INTO crawl_runs (id, website_id, tenant_id, phase, origin, attempt_count, created_at)
                SELECT run_id, website_id, :tenant, phase, 'manual', 1,
                       now() - interval '4 hours' + n * interval '1 second'
                FROM overview_seed
            """),
                {"tenant": admin_user.tenant_id},
            )
            await session.execute(
                sa.text("""
                INSERT INTO crawl_attempts (crawl_run_id, attempt_number, dispatch_id,
                    dispatch_payload, dispatch_attempted_at, dispatched_at, started_at,
                    lease_owner, lease_expires_at)
                SELECT run_id, 1, gen_random_uuid(), '{}'::jsonb, now(), now(),
                    CASE WHEN phase = 'running' THEN now() END,
                    CASE WHEN phase = 'running' THEN 'benchmark' END,
                    CASE WHEN phase = 'running' THEN now() + interval '10 minutes' END
                FROM overview_seed
            """)
            )
        previous = size
        async with db_container(user=admin_user) as container:
            for table in ("websites", "crawl_runs", "crawl_attempts", "spaces"):
                await container.session().execute(sa.text(f"ANALYZE {table}"))
        captured = []

        def record_query(
            connection, cursor, statement, parameters, context, executemany
        ):
            if statement.lstrip().startswith("SELECT") and "crawl_runs" in statement:
                captured.append((statement, parameters))

        sa.event.listen(Engine, "before_cursor_execute", record_query)
        try:
            for _ in range(2):
                assert (
                    await client.get("/api/v1/admin/crawler/", headers=headers)
                ).status_code == 200
            for label, params in (
                ("first", {}),
                ("search", {"search": f"benchmark-source-{size}."}),
            ):
                wall, cpu = [], []
                for _ in range(7):
                    captured.clear()
                    start_wall, start_cpu = (
                        time.perf_counter_ns(),
                        time.process_time_ns(),
                    )
                    response = await client.get(
                        "/api/v1/admin/crawler/", headers=headers, params=params
                    )
                    wall.append((time.perf_counter_ns() - start_wall) / 1e6)
                    cpu.append((time.process_time_ns() - start_cpu) / 1e6)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert data["summary"] == {
                        "ongoing": size // 2,
                        "queued": size // 2,
                        "issues": 0,
                    }
                    assert len(data["items"]) == (50 if label == "first" else 1)
                    assert len(captured) == 2
                print(
                    "CRAWLER_SAMPLE "
                    + json.dumps(
                        {
                            "active": size,
                            "view": label,
                            "wall_ms": wall,
                            "cpu_ms": cpu,
                            "median_ms": statistics.median(wall),
                            "queries": len(captured),
                            "response_bytes": len(response.content),
                        }
                    )
                )
                plans = list(captured)
                async with db_container(user=admin_user) as container:
                    connection = await container.session().connection()
                    for statement, parameters in plans:
                        plan = (
                            await connection.exec_driver_sql(
                                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                                parameters,
                            )
                        ).scalar_one()
                        print(
                            "CRAWLER_PLAN "
                            + json.dumps({"active": size, "view": label, "plan": plan})
                        )
            first = await client.get("/api/v1/admin/crawler/", headers=headers)
            captured.clear()
            second = await client.get(
                "/api/v1/admin/crawler/",
                headers=headers,
                params={"cursor": first.json()["next_cursor"]},
            )
            assert second.status_code == 200, second.text
            assert len(captured) == 3
            assert len(second.json()["items"]) == 50
            assert not (
                {item["run"]["id"] for item in first.json()["items"]}
                & {item["run"]["id"] for item in second.json()["items"]}
            )
            tracemalloc.start()
            response = await client.get("/api/v1/admin/crawler/", headers=headers)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert response.status_code == 200
            print(
                "CRAWLER_MEMORY "
                + json.dumps(
                    {
                        "active": size,
                        "python_peak_bytes": peak,
                        "process_peak_rss_kib_including_setup": resource.getrusage(
                            resource.RUSAGE_SELF
                        ).ru_maxrss,
                    }
                )
            )
        finally:
            sa.event.remove(Engine, "before_cursor_execute", record_query)
        if size == 10000:
            start = time.perf_counter()
            responses = await asyncio.gather(
                *(
                    client.get("/api/v1/admin/crawler/", headers=headers)
                    for _ in range(10)
                )
            )
            assert all(response.status_code == 200 for response in responses)
            print(
                "CRAWLER_CONCURRENT "
                + json.dumps(
                    {"requests": 10, "batch_ms": (time.perf_counter() - start) * 1000}
                )
            )


async def test_admin_crawler_details_scaling(
    client, db_container, admin_user, website_id, headers
):
    """Measure on-demand detail reads with a large source and tenant."""
    async with db_container(user=admin_user) as container:
        session = container.session()
        await session.execute(
            sa.text("""
            INSERT INTO websites (name, url, download_files, crawl_type, update_interval,
                                  size, tenant_id, user_id, embedding_model_id, space_id)
            SELECT NULL, CASE WHEN n <= 11 THEN w.url ELSE 'https://details-' || n || '.example.test' END,
                   false, w.crawl_type, 'never', 0, w.tenant_id, w.user_id, w.embedding_model_id, w.space_id
            FROM generate_series(1, 100000) n CROSS JOIN websites w WHERE w.id = :website
        """),
            {"website": website_id},
        )
        await session.execute(
            sa.text("""
            INSERT INTO info_blobs (text, size, source_id, version_state, user_id,
                                    tenant_id, website_id, embedding_model_id)
            SELECT 'Synthetic indexed document', 128, gen_random_uuid(), 'active',
                   w.user_id, w.tenant_id, w.id, w.embedding_model_id
            FROM generate_series(1, 100000) n CROSS JOIN websites w WHERE w.id = :website
        """),
            {"website": website_id},
        )
        await session.execute(
            sa.text("UPDATE websites SET size = 12800000 WHERE id = :website"),
            {"website": website_id},
        )
        await session.execute(
            sa.text("""
            INSERT INTO crawl_runs (website_id, tenant_id, phase, outcome, origin, finished_at)
            SELECT :website, :tenant, 'terminal', 'succeeded', 'legacy', now() - interval '2 days'
            FROM generate_series(1, 100000)
        """),
            {"website": website_id, "tenant": admin_user.tenant_id},
        )
        run_id = await session.scalar(
            sa.text(
                "SELECT id FROM crawl_runs WHERE website_id = :website ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"website": website_id},
        )
        unmatched_website = await session.scalar(
            sa.text(
                "SELECT id FROM websites WHERE url = 'https://details-100000.example.test'"
            )
        )
        for table in ("websites", "info_blobs", "crawl_runs", "crawl_attempts"):
            await session.execute(sa.text(f"ANALYZE {table}"))

    captured = []

    def record_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT"):
            captured.append((statement, parameters))

    sa.event.listen(Engine, "before_cursor_execute", record_query)
    try:
        for label, url, expected_count in (
            ("details", f"/api/v1/admin/crawler/runs/{run_id}/", None),
            ("history", f"/api/v1/admin/crawler/websites/{website_id}/runs/", 10),
            ("matches", f"/api/v1/admin/crawler/websites/{website_id}/matches/", 10),
            (
                "no_matches",
                f"/api/v1/admin/crawler/websites/{unmatched_website}/matches/",
                0,
            ),
        ):
            for _ in range(2):
                assert (await client.get(url, headers=headers)).status_code == 200
            wall = []
            for _ in range(7):
                captured.clear()
                start = time.perf_counter_ns()
                response = await client.get(url, headers=headers)
                wall.append((time.perf_counter_ns() - start) / 1e6)
                assert response.status_code == 200, response.text
                data = response.json()
                if expected_count is None:
                    assert data["stored_resources"] == 100000
                    assert data["indexed_size"] == 12800000
                else:
                    assert len(data["items"]) == expected_count
            domain_queries = [
                (statement, params)
                for statement, params in captured
                if any(
                    table in statement
                    for table in ("websites", "crawl_runs", "info_blobs")
                )
            ]
            print(
                "CRAWLER_DETAIL_SAMPLE "
                + json.dumps(
                    {
                        "view": label,
                        "websites": 100001,
                        "source_documents": 100000,
                        "source_runs": 100000,
                        "wall_ms": wall,
                        "median_ms": statistics.median(wall),
                        "select_queries_including_auth": len(captured),
                        "domain_queries": len(domain_queries),
                        "response_bytes": len(response.content),
                    }
                )
            )
            async with db_container(user=admin_user) as container:
                connection = await container.session().connection()
                for statement, parameters in domain_queries:
                    plan = (
                        await connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                            parameters,
                        )
                    ).scalar_one()
                    print(
                        "CRAWLER_DETAIL_PLAN "
                        + json.dumps({"view": label, "plan": plan})
                    )
            tracemalloc.start()
            response = await client.get(url, headers=headers)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert response.status_code == 200
            print(
                "CRAWLER_DETAIL_MEMORY "
                + json.dumps({"view": label, "python_peak_bytes": peak})
            )
    finally:
        sa.event.remove(Engine, "before_cursor_execute", record_query)
