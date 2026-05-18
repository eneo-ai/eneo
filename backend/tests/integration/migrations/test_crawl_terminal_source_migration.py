from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202605181000"
TERMINAL_SOURCE_REVISION = "202605191100"


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

    try:
        command.upgrade(cfg, PRE_REVISION)
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _has_column(conn, *, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


def _has_constraint(conn, *, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = %s
              AND constraint_name = %s
            """,
            (table_name, constraint_name),
        )
        return cur.fetchone() is not None


def test_crawl_terminal_source_migration_round_trips(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]

    assert not _has_column(conn, table_name="crawl_runs", column_name="terminal_source")

    command.upgrade(cfg, TERMINAL_SOURCE_REVISION)

    assert _has_column(conn, table_name="crawl_runs", column_name="terminal_source")
    assert _has_constraint(
        conn,
        table_name="crawl_runs",
        constraint_name="ck_crawl_runs_terminal_source",
    )

    command.downgrade(cfg, PRE_REVISION)

    assert not _has_column(conn, table_name="crawl_runs", column_name="terminal_source")

    command.upgrade(cfg, TERMINAL_SOURCE_REVISION)

    assert _has_column(conn, table_name="crawl_runs", column_name="terminal_source")
