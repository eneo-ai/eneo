"""Fresh-chain PostgreSQL contract for removed Flow effect surfaces."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_FLOW_REVISION = "202604101000"
CURRENT_HEAD = "202607111200_file_tenant_fks"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    yield


@pytest.fixture
def fresh_chain_db(test_settings) -> Iterator[tuple[PsycopgConnection, Config]]:
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
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_fresh_chain_excludes_post_input_and_retains_post_output(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    command.upgrade(cfg, "head")

    assert current_revisions(conn) == {CURRENT_HEAD}
    _assert_http_mode_constraints(conn)
    _assert_flow_mcp_schema_removed(conn)

    command.downgrade(cfg, PRE_FLOW_REVISION)
    assert current_revisions(conn) == {PRE_FLOW_REVISION}
    assert not _table_exists(conn, "flow_steps")

    command.upgrade(cfg, "head")
    assert current_revisions(conn) == {CURRENT_HEAD}
    _assert_http_mode_constraints(conn)
    _assert_flow_mcp_schema_removed(conn)


def _assert_http_mode_constraints(conn: PsycopgConnection) -> None:
    input_source = _constraint_definition(conn, "ck_flow_steps_input_source")
    output_mode = _constraint_definition(conn, "ck_flow_steps_output_mode")

    assert "http_get" in input_source
    assert "http_post" not in input_source
    assert "http_post" in output_mode


def _assert_flow_mcp_schema_removed(conn: PsycopgConnection) -> None:
    assert not _column_exists(conn, "flow_steps", "mcp_policy")
    for constraint_name in (
        "ck_flow_resource_bindings_slot_kind",
        "ck_flow_resource_bindings_local_resource_kind",
        "ck_flow_resource_bindings_slot_local_kind_pair",
    ):
        assert (
            "mcp"
            not in _constraint_definition(
                conn,
                constraint_name,
                table_name="flow_resource_bindings",
            ).lower()
        )


def _table_exists(conn: PsycopgConnection, table_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
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
        row = cursor.fetchone()
    return bool(row and row[0])


def _column_exists(conn: PsycopgConnection, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (table_name, column_name),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _constraint_definition(
    conn: PsycopgConnection,
    name: str,
    *,
    table_name: str = "flow_steps",
) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS table_row
              ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, name),
        )
        row = cursor.fetchone()
    assert row is not None
    return str(row[0])
