"""Round-trip the provider-call lifecycle constraint (202609201000).

The revision recreates ck_flow_provider_calls_lifecycle_shape so a rejected
receipt may carry the budget_exhausted reason; the downgrade restores the
previous shape exactly and rewrites any such rows first.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202609181000"
REVISION = "202609201000"
CONSTRAINT = "ck_flow_provider_calls_lifecycle_shape"


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
    command.upgrade(cfg, REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _constraint_definition(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (CONSTRAINT,),
        )
        row = cursor.fetchone()
        assert row is not None, "lifecycle constraint missing"
        return row[0]


def test_upgrade_admits_budget_exhausted_and_keeps_the_other_reasons(round_trip_db):
    definition = _constraint_definition(round_trip_db["conn"])

    assert "budget_exhausted" in definition
    assert "response_format_rejected" in definition
    assert "provider_rejected" in definition
    assert "request_cancelled" in definition


def test_downgrade_restores_the_previous_shape(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]

    command.downgrade(cfg, PRE_REVISION)
    definition = _constraint_definition(conn)

    assert "budget_exhausted" not in definition
    assert "response_format_rejected" in definition
    assert "provider_rejected" in definition

    command.upgrade(cfg, REVISION)
    assert "budget_exhausted" in _constraint_definition(conn)
