"""PostgreSQL migration contract for dropping the unused Flow dependency table."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy.exc import InternalError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607151200_retention_barrier"
MIGRATION_REVISION = "202607221930_drop_step_deps"
TABLE_NAME = "flow_step_dependencies"
SENTINEL_FLOW_ID = "00000000-0000-4000-8000-000000000481"
SENTINEL_PARENT_STEP_ID = "00000000-0000-4000-8000-000000000482"
SENTINEL_CHILD_STEP_ID = "00000000-0000-4000-8000-000000000483"
SENTINEL_TENANT_ID = "00000000-0000-4000-8000-000000000484"


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg13",
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    )
    with postgres:
        postgres.get_connection_url()
        yield postgres


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture
def migration_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRIOR_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _delete_sentinel(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _table_exists(conn) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.flow_step_dependencies')")
        return cursor.fetchone()[0] is not None


def _column_contract(conn) -> dict[str, tuple[str, str, str | None]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (TABLE_NAME,),
        )
        return {
            name: (data_type, nullable, default)
            for name, data_type, nullable, default in cursor
        }


def _constraint_contract(conn) -> dict[str, tuple[str, str]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT constraint_row.conname,
                   constraint_row.contype,
                   pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
            ORDER BY constraint_row.conname
            """,
            (TABLE_NAME,),
        )
        return {
            name: (constraint_type, definition)
            for name, constraint_type, definition in cursor
        }


def _secondary_indexes(conn) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
              AND indexname <> 'flow_step_dependencies_pkey'
            ORDER BY indexname
            """,
            (TABLE_NAME,),
        )
        return dict(cursor)


def _insert_sentinel(conn) -> None:
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = replica")
            cursor.execute(
                """
                INSERT INTO flow_step_dependencies (
                    flow_id, parent_step_id, child_step_id, tenant_id
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    SENTINEL_FLOW_ID,
                    SENTINEL_PARENT_STEP_ID,
                    SENTINEL_CHILD_STEP_ID,
                    SENTINEL_TENANT_ID,
                ),
            )
    finally:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = DEFAULT")


def _delete_sentinel(conn) -> None:
    if not _table_exists(conn):
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = replica")
            cursor.execute(
                "DELETE FROM flow_step_dependencies WHERE flow_id = %s",
                (SENTINEL_FLOW_ID,),
            )
    finally:
        with conn.cursor() as cursor:
            cursor.execute("SET session_replication_role = DEFAULT")


def _assert_reconstructed_schema(conn) -> None:
    assert _column_contract(conn) == {
        "created_at": ("timestamp with time zone", "NO", "now()"),
        "updated_at": ("timestamp with time zone", "NO", "now()"),
        "flow_id": ("uuid", "NO", None),
        "parent_step_id": ("uuid", "NO", None),
        "child_step_id": ("uuid", "NO", None),
        "tenant_id": ("uuid", "NO", None),
    }
    constraints = _constraint_contract(conn)
    assert constraints["flow_step_dependencies_pkey"] == (
        "p",
        "PRIMARY KEY (flow_id, parent_step_id, child_step_id)",
    )
    assert constraints["ck_flow_step_dependencies_no_self_ref"] == (
        "c",
        "CHECK ((parent_step_id <> child_step_id))",
    )
    assert constraints["fk_flow_step_deps_parent_same_flow"] == (
        "f",
        "FOREIGN KEY (flow_id, parent_step_id) REFERENCES flow_steps(flow_id, id) ON DELETE CASCADE",
    )
    assert constraints["fk_flow_step_deps_child_same_flow"] == (
        "f",
        "FOREIGN KEY (flow_id, child_step_id) REFERENCES flow_steps(flow_id, id) ON DELETE CASCADE",
    )
    assert constraints["fk_flow_step_deps_flow_tenant"] == (
        "f",
        "FOREIGN KEY (flow_id, tenant_id) REFERENCES flows(id, tenant_id) ON DELETE CASCADE",
    )
    foreign_key_definitions = {
        definition
        for constraint_type, definition in constraints.values()
        if constraint_type == "f"
    }
    assert foreign_key_definitions == {
        "FOREIGN KEY (flow_id) REFERENCES flows(id) ON DELETE CASCADE",
        "FOREIGN KEY (parent_step_id) REFERENCES flow_steps(id) ON DELETE CASCADE",
        "FOREIGN KEY (child_step_id) REFERENCES flow_steps(id) ON DELETE CASCADE",
        "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE",
        "FOREIGN KEY (flow_id, parent_step_id) REFERENCES flow_steps(flow_id, id) ON DELETE CASCADE",
        "FOREIGN KEY (flow_id, child_step_id) REFERENCES flow_steps(flow_id, id) ON DELETE CASCADE",
        "FOREIGN KEY (flow_id, tenant_id) REFERENCES flows(id, tenant_id) ON DELETE CASCADE",
    }
    indexes = _secondary_indexes(conn)
    assert set(indexes) == {"ix_flow_step_dependencies_tenant_id"}
    assert indexes["ix_flow_step_dependencies_tenant_id"].endswith(
        "USING btree (tenant_id)"
    )


def test_upgrade_preflight_rejects_rows_before_drop(migration_db) -> None:
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    _insert_sentinel(conn)

    with pytest.raises(
        InternalError,
        match="Cannot drop flow_step_dependencies while rows exist",
    ):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _table_exists(conn)
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM flow_step_dependencies")
        assert cursor.fetchone()[0] == 1


def test_upgrade_drops_empty_table_and_downgrade_reconstructs_schema(
    migration_db,
) -> None:
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    _assert_reconstructed_schema(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert not _table_exists(conn)

    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    _assert_reconstructed_schema(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert not _table_exists(conn)
