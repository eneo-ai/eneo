"""Round trip for 202611241000: runs from before the upgrade stay unmarked.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_run_retention_mark_round_trip.py
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611231030"
REVISION = "202611241000"


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the schema revision across the cycle within this module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _store_run_in_a_space_with_a_time(conn) -> str:
    # Without the foreign-key triggers the rows need no tenant or version; the
    # space has a time, so a backfill from it would mark the run.
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            cur.execute(
                "INSERT INTO spaces (name, tenant_id, data_retention_days) "
                "VALUES ('Mark', gen_random_uuid(), 30) RETURNING id, tenant_id"
            )
            space_id, tenant_id = cur.fetchone()
            cur.execute(
                "INSERT INTO flows (name, tenant_id, space_id) "
                "VALUES ('Mark', %s, %s) RETURNING id",
                (tenant_id, space_id),
            )
            (flow_id,) = cur.fetchone()
            cur.execute(
                "INSERT INTO flow_runs (flow_id, flow_version, tenant_id, "
                "principal_type, principal_user_id, status, finished_at) "
                "VALUES (%s, 1, %s, 'user', gen_random_uuid(), 'completed', now()) "
                "RETURNING id",
                (flow_id, tenant_id),
            )
            return cur.fetchone()[0]
        finally:
            cur.execute("SET session_replication_role = DEFAULT")


def _mark(conn, run_id: str) -> bool | None:
    """The run's mark, or None without the column."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'flow_runs' "
            "AND column_name = 'started_under_space_retention'"
        )
        if cur.fetchone() is None:
            return None
        cur.execute(
            "SELECT started_under_space_retention FROM flow_runs WHERE id = %s",
            (run_id,),
        )
        return cur.fetchone()[0]


def test_existing_runs_stay_unmarked_and_downgrade_drops_the_mark(test_settings):
    """Mutants: the upgrade backfills the mark from the space's time, or the
    downgrade leaves the column behind."""
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    try:
        with at_revision(cfg, PRE_REVISION):
            run_id = _store_run_in_a_space_with_a_time(conn)
            assert _mark(conn, run_id) is None

            command.upgrade(cfg, REVISION)
            assert _mark(conn, run_id) is False

            command.downgrade(cfg, PRE_REVISION)
            assert _mark(conn, run_id) is None

            command.upgrade(cfg, REVISION)
            assert _mark(conn, run_id) is False
    finally:
        conn.close()
