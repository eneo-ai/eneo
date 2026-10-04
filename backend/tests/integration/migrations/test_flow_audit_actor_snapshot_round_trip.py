"""Round-trip the flow audit outbox actor snapshot column and actor key indexes (202610021000).

The column is a nullable addition: outbox rows written before the revision stay
valid with no snapshot. The partial indexes serve the FK SET NULL lookup when a
user or API key is deleted. The downgrade drops exactly these.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202609291100"
SNAPSHOT_REVISION = "202610021000"


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
    command.upgrade(cfg, SNAPSHOT_REVISION)
    try:
        yield conn, cfg
    finally:
        command.upgrade(cfg, "head")
        conn.close()


def _snapshot_column(conn) -> tuple[str, str] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'flow_run_audit_outbox'
              AND column_name = 'actor_snapshot'
            """
        )
        return cursor.fetchone()


def _actor_indexes(conn) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = 'flow_run_audit_outbox'
              AND indexname LIKE 'ix_flow_run_audit_outbox_actor%%'
            """
        )
        return dict(cursor.fetchall())


def test_upgrade_adds_the_column_and_actor_indexes_and_downgrade_drops_them(
    round_trip_db,
):
    conn, cfg = round_trip_db
    assert _snapshot_column(conn) == ("jsonb", "YES")
    indexes = _actor_indexes(conn)
    assert set(indexes) == {
        "ix_flow_run_audit_outbox_actor_id",
        "ix_flow_run_audit_outbox_actor_api_key_id",
    }
    assert (
        "WHERE (actor_id IS NOT NULL)" in indexes["ix_flow_run_audit_outbox_actor_id"]
    )

    command.downgrade(cfg, PRE_REVISION)
    assert _snapshot_column(conn) is None
    assert _actor_indexes(conn) == {}

    command.upgrade(cfg, SNAPSHOT_REVISION)
    assert _snapshot_column(conn) == ("jsonb", "YES")
    assert set(_actor_indexes(conn)) == set(indexes)
