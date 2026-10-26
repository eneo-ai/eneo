"""Round-trip test for the sessions api_key_id ON DELETE CASCADE migration.

Verifies that ``202610262130`` makes ``sessions.api_key_id`` cascade from
``api_keys_v2`` and that downgrading restores SET NULL.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_sessions_api_key_cascade_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610261210"
REVISION = "202610262130"

_FK = "FOREIGN KEY (api_key_id) REFERENCES api_keys_v2(id) ON DELETE {}"


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


def _api_key_fk(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'sessions'::regclass "
            "AND conname = 'sessions_api_key_id_fkey'"
        )
        return cur.fetchone()[0]


def test_api_key_fk_cascades_and_downgrade_restores_set_null(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]

    assert _api_key_fk(conn) == _FK.format("CASCADE")

    command.downgrade(cfg, PRE_REVISION)
    assert _api_key_fk(conn) == _FK.format("SET NULL")

    command.upgrade(cfg, REVISION)
    assert _api_key_fk(conn) == _FK.format("CASCADE")
