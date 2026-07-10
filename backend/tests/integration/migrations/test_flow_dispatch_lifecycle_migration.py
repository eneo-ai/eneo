"""Fresh-chain PostgreSQL contract for Flow dispatch lifecycle storage."""

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

FLOW_FOUNDATION_REVISION = "579199d395dd"
PRE_FLOW_REVISION = "202604101000"
CURRENT_HEAD = "202607081035_compose_text"
DISPATCH_COLUMNS = {
    "dispatch_pending_since": ("timestamp with time zone", True, None),
    "dispatch_attempt_count": ("integer", False, "0"),
    "dispatch_last_attempt_at": ("timestamp with time zone", True, None),
    "dispatch_last_error": ("jsonb", True, None),
    "dispatch_next_attempt_at": ("timestamp with time zone", True, None),
    "dispatched_at": ("timestamp with time zone", True, None),
    "dispatch_exhausted_at": ("timestamp with time zone", True, None),
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
    command.upgrade(cfg, PRE_FLOW_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_fresh_chain_creates_dispatch_schema_at_head(fresh_chain_db) -> None:
    conn = fresh_chain_db["conn"]
    cfg = fresh_chain_db["cfg"]

    assert not _table_exists(conn, "flow_runs")
    command.upgrade(cfg, FLOW_FOUNDATION_REVISION)

    assert _dispatch_columns(conn) == DISPATCH_COLUMNS
    assert _index_shape(conn) == (
        ("tenant_id", "dispatch_next_attempt_at", "id"),
        "((status)::text = 'queued'::text)",
        "dispatch_next_attempt_at IS NOT NULL",
        "dispatch_exhausted_at IS NULL",
    )
    assert _constraint_is_validated(
        conn, "ck_flow_runs_dispatch_attempt_count_nonnegative"
    )
    assert _constraint_is_validated(conn, "ck_flow_runs_dispatch_last_error_object")

    command.upgrade(cfg, "head")

    assert current_revisions(conn) == {CURRENT_HEAD}
    assert _dispatch_columns(conn) == DISPATCH_COLUMNS
    assert "dispatch_attempt_count >= 0" in _constraint_definition(
        conn, "ck_flow_runs_dispatch_attempt_count_nonnegative"
    )
    assert "jsonb_typeof(dispatch_last_error) = 'object'::text" in (
        _constraint_definition(conn, "ck_flow_runs_dispatch_last_error_object")
    )
    assert "dispatch_failure" in _constraint_definition(
        conn, "ck_flow_run_audit_outbox_source"
    )


def test_fresh_chain_downgrades_before_flow_and_replays_to_head(
    fresh_chain_db,
) -> None:
    conn = fresh_chain_db["conn"]
    cfg = fresh_chain_db["cfg"]

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_FLOW_REVISION)
    assert current_revisions(conn) == {PRE_FLOW_REVISION}
    assert not _table_exists(conn, "flow_runs")

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    assert _dispatch_columns(conn) == DISPATCH_COLUMNS


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


def _dispatch_columns(conn) -> dict[str, tuple[str, bool, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'flow_runs'
              AND column_name = ANY(%s)
            """,
            (list(DISPATCH_COLUMNS),),
        )
        return {
            str(name): (str(data_type), nullable == "YES", default)
            for name, data_type, nullable, default in cur.fetchall()
        }


def _index_shape(conn) -> tuple[tuple[str, ...], str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(attribute.attname ORDER BY key.ordinality),
                   pg_get_expr(index_metadata.indpred, index_metadata.indrelid)
            FROM pg_class index_row
            JOIN pg_index index_metadata
              ON index_metadata.indexrelid = index_row.oid
            JOIN pg_class table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN unnest(index_metadata.indkey)
              WITH ORDINALITY AS key(attnum, ordinality)
              ON true
            JOIN pg_attribute attribute
              ON attribute.attrelid = table_row.oid
             AND attribute.attnum = key.attnum
            WHERE index_row.relname = 'ix_flow_runs_queued_dispatch_due'
            GROUP BY index_metadata.indpred, index_metadata.indrelid
            """
        )
        row = cur.fetchone()
    assert row is not None
    predicate = str(row[1])
    return (
        (
            tuple(row[0]),
            "((status)::text = 'queued'::text)",
            "dispatch_next_attempt_at IS NOT NULL",
            "dispatch_exhausted_at IS NULL",
        )
        if all(
            fragment in predicate
            for fragment in (
                "((status)::text = 'queued'::text)",
                "dispatch_next_attempt_at IS NOT NULL",
                "dispatch_exhausted_at IS NULL",
            )
        )
        else (tuple(row[0]), predicate, "", "")
    )


def _constraint_is_validated(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT convalidated FROM pg_constraint WHERE conname = %s",
            (name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def _constraint_definition(conn, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (name,),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])
