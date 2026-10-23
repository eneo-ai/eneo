"""Round-trip test for the rerank_models migration.

Verifies that ``202610141000`` creates the catalog table and its indexes on
upgrade, removes them on downgrade, and recreates them on a second upgrade.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_rerank_models_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610131800"
REVISION = "202610141000"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override shared cleanup_database so schema revisions persist across
    downgrade/upgrade cycles within this module.
    """
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override shared seed_default_models — this module seeds no data."""
    yield


@pytest.fixture
def round_trip_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    command.upgrade(cfg, REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _table_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.rerank_models') IS NOT NULL")
        return bool(cur.fetchone()[0])


def _assistant_column_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'assistants' AND column_name = 'rerank_model_id'"
        )
        return cur.fetchone() is not None


def _index_names(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'rerank_models'"
        )
        return {row[0] for row in cur.fetchall()}


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        return row[0] if row else None


class TestRerankModelsRoundTrip:
    def test_upgrade_creates_table_and_indexes(self, round_trip_db):
        conn = round_trip_db["conn"]

        assert _current_revision(conn) == REVISION
        assert _table_exists(conn)
        assert {
            "ix_rerank_models_tenant_id",
            "ix_rerank_models_provider_id",
            "ix_rerank_models_deleted_at",
            "uq_rerank_models_active_nickname",
        } <= _index_names(conn)
        assert _assistant_column_exists(conn)

    def test_downgrade_drops_table_and_assistant_column(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)

        assert _current_revision(conn) == PRE_REVISION
        assert not _table_exists(conn)
        assert not _assistant_column_exists(conn)

    def test_round_trip_recreates_table(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        assert not _table_exists(conn)

        command.upgrade(cfg, REVISION)
        assert _table_exists(conn)
        assert "uq_rerank_models_active_nickname" in _index_names(conn)
