from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import execute_values

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_INDEX_REVISION = "202605141700"
INDEX_REVISION = "202605142300"
JOBS_ACTIVE_INDEX = "idx_jobs_active_crawl_created_at_id"
CRAWL_RUNS_WEBSITE_JOB_INDEX = "idx_crawl_runs_website_job_lookup"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def active_lookup_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    _normalize_to_revision(conn, cfg, PRE_INDEX_REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT version_num FROM alembic_version")
        except psycopg2.errors.UndefinedTable:
            return None
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0])


def _normalize_to_revision(conn, cfg: Config, revision: str) -> None:
    current_revision = _current_revision(conn)
    if current_revision is None:
        command.upgrade(cfg, revision)
    elif current_revision != revision:
        command.downgrade(cfg, revision)

    normalized_revision = _current_revision(conn)
    assert normalized_revision == revision


def _seed_prerequisites(conn) -> dict[str, UUID]:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    user_id = uuid4()
    embedding_model_id = uuid4()
    website_id = uuid4()
    other_website_id = uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state, created_at, updated_at)
            VALUES (%s, %s, 1000000, 'active', %s, %s)
            """,
            (str(tenant_id), f"active-lookup-{tenant_id.hex[:8]}", now, now),
        )
        cur.execute(
            """
            INSERT INTO users (
                id, email, state, used_tokens, tenant_id, created_at, updated_at
            )
            VALUES (%s, %s, 'active', 0, %s, %s, %s)
            """,
            (
                str(user_id),
                f"active-lookup-{user_id.hex[:8]}@example.com",
                str(tenant_id),
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO embedding_models (
                id, name, open_source, dimensions, max_input, max_batch_size,
                family, stability, hosting, created_at, updated_at
            )
            VALUES (
                %s, %s, false, 1536, 8192, 100,
                'openai', 'stable', 'cloud', %s, %s
            )
            """,
            (
                str(embedding_model_id),
                f"active-lookup-embedding-{embedding_model_id.hex[:8]}",
                now,
                now,
            ),
        )
        execute_values(
            cur,
            """
            INSERT INTO websites (
                id, name, url, download_files, crawl_type, update_interval, size,
                tenant_id, user_id, embedding_model_id, created_at, updated_at
            )
            VALUES %s
            """,
            [
                (
                    str(website_id),
                    "Active lookup",
                    f"https://active-lookup-{website_id.hex[:8]}.example.com",
                    True,
                    "CRAWL",
                    "never",
                    0,
                    str(tenant_id),
                    str(user_id),
                    str(embedding_model_id),
                    now,
                    now,
                ),
                (
                    str(other_website_id),
                    "Other active lookup",
                    f"https://active-lookup-{other_website_id.hex[:8]}.example.com",
                    True,
                    "CRAWL",
                    "never",
                    0,
                    str(tenant_id),
                    str(user_id),
                    str(embedding_model_id),
                    now,
                    now,
                ),
            ],
        )

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "website_id": website_id,
        "other_website_id": other_website_id,
    }


def _insert_job_crawl_run(
    conn,
    *,
    ids: dict[str, UUID],
    website_id: UUID,
    status: str,
    created_at: datetime,
    task: str = "crawl",
) -> UUID:
    job_id = uuid4()
    run_id = uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                id, user_id, task, status, result_location, name,
                finished_at, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, NULL, 'Active lookup test', NULL, %s, %s)
            """,
            (
                str(job_id),
                str(ids["user_id"]),
                task,
                status,
                created_at,
                created_at,
            ),
        )
        cur.execute(
            """
            INSERT INTO crawl_runs (
                id, tenant_id, website_id, job_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                str(run_id),
                str(ids["tenant_id"]),
                str(website_id),
                str(job_id),
                created_at,
                created_at,
            ),
        )

    return job_id


def _bulk_insert_inactive_runs(
    conn,
    *,
    ids: dict[str, UUID],
    website_id: UUID,
    count: int,
) -> None:
    now = datetime.now(timezone.utc)
    job_rows = []
    crawl_run_rows = []
    for index in range(count):
        job_id = uuid4()
        run_id = uuid4()
        created_at = now - timedelta(minutes=index)
        job_rows.append(
            (
                str(job_id),
                str(ids["user_id"]),
                "crawl",
                "complete",
                None,
                "Inactive active lookup test",
                created_at,
                created_at,
                created_at,
            )
        )
        crawl_run_rows.append(
            (
                str(run_id),
                str(ids["tenant_id"]),
                str(website_id),
                str(job_id),
                created_at,
                created_at,
            )
        )

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO jobs (
                id, user_id, task, status, result_location, name,
                finished_at, created_at, updated_at
            )
            VALUES %s
            """,
            job_rows,
        )
        execute_values(
            cur,
            """
            INSERT INTO crawl_runs (
                id, tenant_id, website_id, job_id, created_at, updated_at
            )
            VALUES %s
            """,
            crawl_run_rows,
        )


def _active_job_lookup(conn, website_id: UUID) -> UUID | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT j.id
            FROM jobs j
            JOIN crawl_runs cr ON cr.job_id = j.id
            WHERE cr.website_id = %s
                AND j.task = 'crawl'
                AND j.status IN ('queued', 'in progress')
            ORDER BY j.created_at ASC
            LIMIT 1
            """,
            (str(website_id),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))


def _index_definitions(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
                AND tablename IN ('jobs', 'crawl_runs')
            """
        )
        return {str(name): str(definition) for name, definition in cur.fetchall()}


def _explain_lookup(conn, website_id: UUID) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute("ANALYZE jobs")
        cur.execute("ANALYZE crawl_runs")
        cur.execute(
            """
            EXPLAIN (FORMAT JSON)
            SELECT j.id
            FROM jobs j
            JOIN crawl_runs cr ON cr.job_id = j.id
            WHERE cr.website_id = %s
                AND j.task = 'crawl'
                AND j.status IN ('queued', 'in progress')
            ORDER BY j.created_at ASC
            LIMIT 1
            """,
            (str(website_id),),
        )
        rows = cur.fetchone()
    assert rows is not None
    explain_result = rows[0]
    assert isinstance(explain_result, list)
    plan = explain_result[0]["Plan"]
    assert isinstance(plan, dict)
    return plan


def _plan_nodes(plan: dict[str, object]):
    yield plan
    child_plans = plan.get("Plans")
    if not isinstance(child_plans, list):
        return
    for child in child_plans:
        assert isinstance(child, dict)
        yield from _plan_nodes(child)


def _plan_relation_has_seq_scan(
    plan: dict[str, object],
    *,
    relation_name: str,
) -> bool:
    return any(
        node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == relation_name
        for node in _plan_nodes(plan)
    )


def _plan_index_names(plan: dict[str, object]) -> set[str]:
    return {
        str(node.get("Index Name"))
        for node in _plan_nodes(plan)
        if node.get("Index Name") is not None
    }


class TestActiveCrawlLookupIndexes:
    def test_migration_adds_reversible_indexes_and_improves_lookup_plan(
        self, active_lookup_db
    ):
        conn = active_lookup_db["conn"]
        cfg = active_lookup_db["cfg"]
        ids = _seed_prerequisites(conn)
        website_id = ids["website_id"]
        other_website_id = ids["other_website_id"]
        now = datetime.now(timezone.utc)

        _bulk_insert_inactive_runs(
            conn,
            ids=ids,
            website_id=website_id,
            count=12_000,
        )
        non_crawl_job_id = _insert_job_crawl_run(
            conn,
            ids=ids,
            website_id=website_id,
            status="queued",
            created_at=now - timedelta(hours=4),
            task="transcription",
        )
        expected_job_id = _insert_job_crawl_run(
            conn,
            ids=ids,
            website_id=website_id,
            status="queued",
            created_at=now - timedelta(hours=2),
        )
        _insert_job_crawl_run(
            conn,
            ids=ids,
            website_id=website_id,
            status="in progress",
            created_at=now - timedelta(hours=1),
        )
        _insert_job_crawl_run(
            conn,
            ids=ids,
            website_id=other_website_id,
            status="queued",
            created_at=now - timedelta(hours=3),
        )

        assert _active_job_lookup(conn, website_id) == expected_job_id
        assert _active_job_lookup(conn, website_id) != non_crawl_job_id

        pre_upgrade_plan = _explain_lookup(conn, website_id)
        assert _plan_relation_has_seq_scan(pre_upgrade_plan, relation_name="crawl_runs")

        command.upgrade(cfg, INDEX_REVISION)

        index_definitions = _index_definitions(conn)
        assert JOBS_ACTIVE_INDEX in index_definitions
        assert CRAWL_RUNS_WEBSITE_JOB_INDEX in index_definitions
        jobs_index_definition = index_definitions[JOBS_ACTIVE_INDEX]
        assert "(task)::text = 'crawl'::text" in jobs_index_definition
        assert "(status)::text = ANY" in jobs_index_definition
        assert _active_job_lookup(conn, website_id) == expected_job_id

        post_upgrade_plan = _explain_lookup(conn, website_id)
        index_names = _plan_index_names(post_upgrade_plan)
        assert {JOBS_ACTIVE_INDEX, CRAWL_RUNS_WEBSITE_JOB_INDEX} <= index_names
        assert not any(
            node.get("Node Type") == "Seq Scan"
            and node.get("Relation Name") in {"jobs", "crawl_runs"}
            for node in _plan_nodes(post_upgrade_plan)
        )

        command.downgrade(cfg, PRE_INDEX_REVISION)

        downgraded_index_definitions = _index_definitions(conn)
        assert JOBS_ACTIVE_INDEX not in downgraded_index_definitions
        assert CRAWL_RUNS_WEBSITE_JOB_INDEX not in downgraded_index_definitions
