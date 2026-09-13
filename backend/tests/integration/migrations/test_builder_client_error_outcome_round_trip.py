"""Round-trip the builder client error outcome columns (202609131200).

The four outcome columns are nullable additions: rows observed before the
revision stay valid, and the downgrade drops exactly those columns and no
other data.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202609081000"
OUTCOME_REVISION = "202609131200"
TABLE = "builder_client_errors"
OUTCOME_COLUMNS = (
    "surface",
    "presented_as",
    "first_action",
    "first_action_received_at",
)


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
    command.upgrade(cfg, OUTCOME_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _outcome_columns(conn) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = ANY(%s)
            """,
            (TABLE, list(OUTCOME_COLUMNS)),
        )
        return {name: nullable for name, nullable in cursor.fetchall()}


def _insert_observed_error(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"client-error-outcome-{uuid4().hex[:8]}",),
        )
        tenant_id = cursor.fetchone()[0]
        cursor.execute(
            f"""
            INSERT INTO {TABLE}
                (tenant_id, client_event_id, phase, category, code, request_id)
            VALUES (%s, %s, 'planner', 'upstream', 'planner_upstream_error', %s)
            RETURNING id
            """,
            (tenant_id, str(uuid4()), uuid4().hex),
        )
        return cursor.fetchone()[0]


def _row_exists(conn, error_id: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {TABLE} WHERE id = %s", (error_id,))
        return cursor.fetchone() is not None


def test_upgrade_adds_nullable_outcome_columns_and_keeps_observed_rows(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    command.downgrade(cfg, PRE_REVISION)
    assert _outcome_columns(conn) == {}
    error_id = _insert_observed_error(conn)

    command.upgrade(cfg, OUTCOME_REVISION)

    assert _outcome_columns(conn) == {name: "YES" for name in OUTCOME_COLUMNS}
    assert _row_exists(conn, error_id)
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT surface, presented_as, first_action FROM {TABLE} WHERE id = %s",
            (error_id,),
        )
        assert cursor.fetchone() == (None, None, None)


def test_downgrade_drops_only_the_outcome_columns(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    error_id = _insert_observed_error(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {TABLE} SET surface = 'generation', first_action = 'retry_requested'"
            " WHERE id = %s",
            (error_id,),
        )

    command.downgrade(cfg, PRE_REVISION)

    assert _outcome_columns(conn) == {}
    assert _row_exists(conn, error_id)
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT code FROM {TABLE} WHERE id = %s", (error_id,))
        assert cursor.fetchone() == ("planner_upstream_error",)

    # Up again: the columns return, empty, and the row is still there.
    command.upgrade(cfg, OUTCOME_REVISION)
    assert set(_outcome_columns(conn)) == set(OUTCOME_COLUMNS)
    assert _row_exists(conn, error_id)
