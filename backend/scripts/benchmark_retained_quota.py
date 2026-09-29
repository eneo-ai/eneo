"""Measure real retained-size SQL and concurrent commit guards on disposable PostgreSQL.

Requires development dependencies and Docker. No application database is used.
uv run python scripts/benchmark_retained_quota.py --output /tmp/quota-benchmark.json
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

import psycopg2
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.admin.quota_service import enforce_quota_on_commit
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.info_blobs.info_blob_repo import InfoBlobRepository


async def concurrent_commits(url, tenant_id, user_id):
    engine = create_async_engine(url, pool_size=8, max_overflow=0)
    sessions = async_sessionmaker(engine)
    timings = []
    query_counts = []
    waits = []
    sql_started = {}
    count = 0

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(connection, cursor, statement, parameters, context, executemany):
        nonlocal count
        count += 1
        sql_started[id(context)] = time.perf_counter()

    @sa.event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(connection, cursor, statement, parameters, context, executemany):
        elapsed = time.perf_counter() - sql_started.pop(id(context))
        if "FOR NO KEY UPDATE" in statement:
            waits.append(elapsed * 1000)

    async def publish():
        async with sessions() as session:
            async with session.begin():
                session.add(
                    InfoBlobs(
                        id=uuid4(),
                        source_id=uuid4(),
                        version_state="active",
                        tenant_id=tenant_id,
                        user_id=user_id,
                        text="Published knowledge",
                        size=1024,
                    )
                )
                await session.flush()
                enforce_quota_on_commit(session, tenant_id=tenant_id, user_id=user_id)
                started = time.perf_counter()
            timings.append((time.perf_counter() - started) * 1000)

    try:
        for _ in range(3):
            before_count = count
            await asyncio.gather(*(publish() for _ in range(8)))
            query_counts.append(count - before_count)
    finally:
        await engine.dispose()
    return {
        "publishers": 8,
        "waves": 3,
        "sql_queries_per_wave": query_counts,
        "commit_p50_ms": round(sorted(timings)[len(timings) // 2], 2),
        "commit_p95_ms": round(sorted(timings)[int((len(timings) - 1) * 0.95)], 2),
        "commit_max_ms": round(max(timings), 2),
        "quota_lock_roundtrip_max_ms": round(max(waits), 2),
    }


def benchmark(output: Path):
    results = {
        "postgres": "pgvector/pgvector:pg16",
        "target": "p95 final commit below 250 ms at 8 concurrent publishers; warm tenant SUM below 50 ms",
        "cases": [],
    }
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        tenant_ids = [uuid4(), uuid4()]
        user_ids = [uuid4(), uuid4()]
        with psycopg2.connect(url.replace("+psycopg2", "")) as connection:
            with connection.cursor() as cursor:
                for tenant_id, user_id in zip(tenant_ids, user_ids):
                    cursor.execute(
                        "INSERT INTO tenants (id, name, quota_limit, state) VALUES (%s, %s, 1000000000000, 'active')",
                        (str(tenant_id), str(tenant_id)),
                    )
                    cursor.execute(
                        "INSERT INTO users (id, tenant_id, email, used_tokens, state, quota_limit) VALUES (%s, %s, %s, 0, 'active', 1000000000000)",
                        (str(user_id), str(tenant_id), f"{user_id}@example.test"),
                    )
            connection.commit()
            for rows in (10000, 100000, 1000000):
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM info_blobs")
                    for tenant_id, user_id in zip(tenant_ids, user_ids):
                        cursor.execute(
                            """INSERT INTO info_blobs (id, source_id, version_state, tenant_id, user_id, text, size)
                            SELECT gen_random_uuid(), gen_random_uuid(), CASE WHEN n %% 8 = 0 THEN 'active' ELSE 'superseded' END,
                            %s, %s, 'Retained knowledge', 1024 FROM generate_series(1, %s) n""",
                            (str(tenant_id), str(user_id), rows // 2),
                        )
                    cursor.execute("ANALYZE info_blobs")
                    cursor.execute("ANALYZE users")
                connection.commit()
                plans = {}
                with connection.cursor() as cursor:
                    for name, statement in (
                        (
                            "tenant",
                            InfoBlobRepository.retained_size_of_tenant_stmt(
                                tenant_ids[0]
                            ),
                        ),
                        (
                            "user",
                            InfoBlobRepository.retained_size_of_user_stmt(user_ids[0]),
                        ),
                    ):
                        sql = str(
                            statement.compile(
                                dialect=sa.dialects.postgresql.dialect(),
                                compile_kwargs={"literal_binds": True},
                            )
                        )
                        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
                        first = cursor.fetchone()[0][0]
                        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
                        warm = cursor.fetchone()[0][0]
                        plans[name] = {"first": first, "warm": warm}
                connection.commit()
                commits = asyncio.run(
                    concurrent_commits(
                        url.replace("+psycopg2", "+asyncpg"), tenant_ids[0], user_ids[0]
                    )
                )
                results["cases"].append(
                    {
                        "retained_rows_total": rows,
                        "retained_rows_per_tenant": rows // 2,
                        "versions_per_active_row": 8,
                        "plans": plans,
                        "commits": commits,
                    }
                )
                print(
                    json.dumps(
                        {
                            "rows": rows,
                            "tenant_sum_warm_ms": plans["tenant"]["warm"][
                                "Execution Time"
                            ],
                            "user_sum_warm_ms": plans["user"]["warm"]["Execution Time"],
                            **commits,
                        }
                    ),
                    flush=True,
                )
    output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    benchmark(parser.parse_args().output)
