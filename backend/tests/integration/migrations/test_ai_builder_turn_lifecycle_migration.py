"""Fresh-chain PostgreSQL contract for AI Builder accepted-turn storage."""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_BUILDER_REVISION = "579199d395dd"
BUILDER_FOUNDATION_REVISION = "202603121400"
CURRENT_HEAD = "202607081035_compose_text"
TURN_COLUMNS = {
    "latest_turn_id": ("uuid", True, None),
    "latest_turn_request_fingerprint": ("character varying", True, 64),
    "latest_turn_request_jsonb": ("jsonb", True, None),
    "latest_turn_state": ("character varying", True, 32),
    "latest_turn_message_id": ("uuid", True, None),
    "latest_turn_error_jsonb": ("jsonb", True, None),
}


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
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
def fresh_chain_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    reset_public_schema(conn)
    command.upgrade(cfg, PRE_BUILDER_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_fresh_chain_creates_strict_latest_turn_shape(fresh_chain_db) -> None:
    conn = fresh_chain_db["conn"]
    cfg = fresh_chain_db["cfg"]

    assert not _table_exists(conn, "builder_sessions")
    command.upgrade(cfg, BUILDER_FOUNDATION_REVISION)

    assert _turn_columns(conn) == TURN_COLUMNS
    all_or_none = _constraint_definition(
        conn,
        "ck_builder_sessions_latest_turn_all_or_none",
    )
    assert "latest_turn_request_jsonb IS NULL" in all_or_none
    assert "latest_turn_request_jsonb IS NOT NULL" in all_or_none
    assert "latest_turn_error_jsonb IS NULL" in all_or_none
    error_constraint = _constraint_definition(
        conn,
        "ck_builder_sessions_latest_turn_error_committed",
    )
    assert "latest_turn_error_jsonb IS NULL" in error_constraint
    assert "latest_turn_state" in error_constraint
    assert "'committed'" in error_constraint
    state_constraint = _constraint_definition(
        conn,
        "ck_builder_sessions_latest_turn_state",
    )
    for state in (
        "open",
        "processing",
        "committed",
        "failed_before_provider",
        "provider_outcome_unknown",
    ):
        assert f"'{state}'" in state_constraint
    assert "char_length" in _constraint_definition(
        conn,
        "ck_builder_sessions_latest_turn_fingerprint_length",
    )

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    assert _turn_columns(conn) == TURN_COLUMNS


def test_fresh_chain_downgrades_before_builder_and_replays_to_head(
    fresh_chain_db,
) -> None:
    conn = fresh_chain_db["conn"]
    cfg = fresh_chain_db["cfg"]

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_BUILDER_REVISION)
    assert PRE_BUILDER_REVISION in current_revisions(conn)
    assert not _table_exists(conn, "builder_sessions")

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    assert _turn_columns(conn) == TURN_COLUMNS


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
            )
            """,
            (table_name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _turn_columns(conn) -> dict[str, tuple[str, bool, int | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'builder_sessions'
              AND column_name = ANY(%s)
            """,
            (list(TURN_COLUMNS),),
        )
        return {
            str(name): (
                str(data_type),
                nullable == "YES",
                int(maximum_length) if maximum_length is not None else None,
            )
            for name, data_type, nullable, maximum_length in cur.fetchall()
        }


def _constraint_definition(conn, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (name,),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])
