from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_BACKFILL_REVISION = "202605152115"
BACKFILL_REVISION = "202605161200"

# The migration filters on `jobs.result_location` (the table that carries
# the worker exception text), not on a `result_location` column on
# `crawl_runs` (which does not exist on this branch — see CrawlRuns model).
HEARTBEAT_RESULT_LOCATION = (
    "Crawl preempted: heartbeat failures exceeded threshold (3/3)"
)
UNRELATED_RESULT_LOCATION = "Crawl failed for https://example.com: no pages returned"
# Runtime-typed CRAWL_HEARTBEAT_FAILED rows can be linked to a job whose
# `result_location` does NOT carry the heartbeat-message marker. We pick a
# `result_location` that does not match the LIKE filter so the bounded
# downgrade predicate leaves the row untouched (realistic when the runtime
# write path normalized the message, truncated it, or set the outcome on a
# row whose `jobs.result_location` was independently overwritten).
RUNTIME_TYPED_RESULT_LOCATION = "Crawl preempted: shutdown signal"


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
        try:
            command.downgrade(cfg, revision)
        except Exception:
            command.upgrade(cfg, revision)

    normalized = _current_revision(conn)
    assert normalized == revision


@pytest.fixture
def heartbeat_backfill_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)

    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    _normalize_to_revision(conn, cfg, PRE_BACKFILL_REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _seed_prerequisites(conn) -> dict[str, UUID]:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    user_id = uuid4()
    embedding_model_id = uuid4()
    website_id = uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state, created_at, updated_at)
            VALUES (%s, %s, 1000000, 'active', %s, %s)
            """,
            (str(tenant_id), f"heartbeat-backfill-{tenant_id.hex[:8]}", now, now),
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
                f"heartbeat-backfill-{user_id.hex[:8]}@example.com",
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
                f"heartbeat-backfill-embedding-{embedding_model_id.hex[:8]}",
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO websites (
                id, name, url, download_files, crawl_type, update_interval, size,
                tenant_id, user_id, embedding_model_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, true, 'CRAWL', 'never', 0, %s, %s, %s, %s, %s)
            """,
            (
                str(website_id),
                "Heartbeat backfill",
                f"https://heartbeat-backfill-{website_id.hex[:8]}.example.com",
                str(tenant_id),
                str(user_id),
                str(embedding_model_id),
                now,
                now,
            ),
        )

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "website_id": website_id,
    }


def _insert_crawl_run(
    conn,
    *,
    ids: dict[str, UUID],
    outcome_code: str,
    result_location: str | None,
) -> UUID:
    now = datetime.now(timezone.utc)
    run_id = uuid4()
    job_id = uuid4()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                id, user_id, task, status, result_location, name,
                finished_at, created_at, updated_at
            )
            VALUES (%s, %s, 'crawl', 'failed', %s, 'Heartbeat backfill test', %s, %s, %s)
            """,
            (
                str(job_id),
                str(ids["user_id"]),
                result_location,
                now,
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO crawl_runs (
                id, tenant_id, website_id, job_id,
                pages_crawled, files_downloaded,
                pages_failed, files_failed,
                pages_source_retained,
                pages_hash_retained, files_hash_retained,
                files_too_large_skipped,
                failure_summary, outcome_code,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s,
                0, 0,
                0, 0,
                0,
                0, 0,
                0,
                NULL, %s,
                %s, %s
            )
            """,
            (
                str(run_id),
                str(ids["tenant_id"]),
                str(ids["website_id"]),
                str(job_id),
                outcome_code,
                now,
                now,
            ),
        )

    return run_id


def _fetch_outcome(conn, run_id: UUID) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome_code FROM crawl_runs WHERE id = %s",
            (str(run_id),),
        )
        row = cur.fetchone()
    assert row is not None, f"crawl_run {run_id} was deleted unexpectedly"
    return row[0]


class TestHeartbeatFailedBackfill:
    def test_upgrade_flips_only_heartbeat_unknown_rows_and_downgrade_reverts_only_them(
        self, heartbeat_backfill_db
    ):
        """
        Spec contract:

        Insert 4 rows BEFORE upgrade:
          (a) UNKNOWN_CRAWL_ERROR + heartbeat message       → must flip
          (b) UNKNOWN_CRAWL_ERROR + unrelated message       → must NOT flip
          (c) CRAWL_HEARTBEAT_FAILED (runtime-typed) already → must stay,
                                                                AND must
                                                                survive
                                                                downgrade
          (d) UNKNOWN_CRAWL_ERROR + NULL result_location    → must NOT flip

        On downgrade, only (a) reverts to UNKNOWN_CRAWL_ERROR; (c) stays
        CRAWL_HEARTBEAT_FAILED because its `result_location` does not match
        the bounded heartbeat-message LIKE filter that downgrade uses.
        """
        conn = heartbeat_backfill_db["conn"]
        cfg = heartbeat_backfill_db["cfg"]
        ids = _seed_prerequisites(conn)

        run_a = _insert_crawl_run(
            conn,
            ids=ids,
            outcome_code="UNKNOWN_CRAWL_ERROR",
            result_location=HEARTBEAT_RESULT_LOCATION,
        )
        run_b = _insert_crawl_run(
            conn,
            ids=ids,
            outcome_code="UNKNOWN_CRAWL_ERROR",
            result_location=UNRELATED_RESULT_LOCATION,
        )
        run_c = _insert_crawl_run(
            conn,
            ids=ids,
            outcome_code="CRAWL_HEARTBEAT_FAILED",
            # NOT the heartbeat-message marker — represents a runtime-typed
            # row whose result_location doesn't echo the worker exception
            # text. The bounded downgrade predicate must leave it alone.
            result_location=RUNTIME_TYPED_RESULT_LOCATION,
        )
        run_d = _insert_crawl_run(
            conn,
            ids=ids,
            outcome_code="UNKNOWN_CRAWL_ERROR",
            result_location=None,
        )

        # --- Upgrade --------------------------------------------------------
        command.upgrade(cfg, BACKFILL_REVISION)

        assert _fetch_outcome(conn, run_a) == "CRAWL_HEARTBEAT_FAILED", (
            "(a) UNKNOWN + heartbeat-message row must be backfilled"
        )
        assert _fetch_outcome(conn, run_b) == "UNKNOWN_CRAWL_ERROR", (
            "(b) UNKNOWN + unrelated message must NOT flip"
        )
        assert _fetch_outcome(conn, run_c) == "CRAWL_HEARTBEAT_FAILED", (
            "(c) already-typed row must remain CRAWL_HEARTBEAT_FAILED"
        )
        assert _fetch_outcome(conn, run_d) == "UNKNOWN_CRAWL_ERROR", (
            "(d) UNKNOWN + NULL result_location must NOT flip"
        )

        # --- Downgrade ------------------------------------------------------
        command.downgrade(cfg, PRE_BACKFILL_REVISION)

        assert _fetch_outcome(conn, run_a) == "UNKNOWN_CRAWL_ERROR", (
            "(a) must revert to UNKNOWN_CRAWL_ERROR on downgrade"
        )
        assert _fetch_outcome(conn, run_b) == "UNKNOWN_CRAWL_ERROR", (
            "(b) must remain UNKNOWN_CRAWL_ERROR (untouched)"
        )
        assert _fetch_outcome(conn, run_c) == "CRAWL_HEARTBEAT_FAILED", (
            "(c) must still be CRAWL_HEARTBEAT_FAILED — its result_location "
            "does not match the heartbeat-message LIKE filter, so the "
            "bounded downgrade predicate leaves it alone"
        )
        assert _fetch_outcome(conn, run_d) == "UNKNOWN_CRAWL_ERROR", (
            "(d) must remain UNKNOWN_CRAWL_ERROR"
        )
