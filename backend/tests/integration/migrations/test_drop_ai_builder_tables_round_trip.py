"""Round-trip the removal of the AI Builder's tables and permissions (202610212200).

The upgrade drops the four builder tables and takes the two builder
permissions out of every role. The downgrade recreates the tables empty, with
the columns they had, and gives the permissions back to predefined Owner roles
only.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.migration_isolation

PRE_REVISION = "202610212100"
DROP_REVISION = "202610212200"
_TIMESTAMPS = {"created_at", "updated_at"}
# The columns 202608201200, 202608241100 and 202609131200 left the tables with.
COLUMNS = {
    "builder_sessions": {
        "id",
        "tenant_id",
        "space_id",
        "flow_id",
        "target_kind",
        "status",
        "actor_user_id",
        "conversation",
        "active_request_id",
        "lock_token",
        "locked_at",
        "lock_expires_at",
        "latest_plan_id",
        "planning_state_jsonb",
        "planning_state_version",
        "latest_turn_id",
        "latest_turn_request_fingerprint",
        "latest_turn_request_jsonb",
        "latest_turn_state",
        "latest_turn_message_id",
        "latest_turn_error_jsonb",
        *_TIMESTAMPS,
    },
    "builder_plans": {
        "id",
        "session_id",
        "tenant_id",
        "status",
        "proposal_json",
        "spec_hash",
        *_TIMESTAMPS,
    },
    "builder_session_files": {"session_id", "file_id", "tenant_id", *_TIMESTAMPS},
    "builder_client_errors": {
        "id",
        "tenant_id",
        "user_id",
        "session_id",
        "client_event_id",
        "phase",
        "category",
        "code",
        "request_id",
        "surface",
        "presented_as",
        "first_action",
        "first_action_received_at",
        *_TIMESTAMPS,
    },
}
TABLES = set(COLUMNS)
PERMISSIONS = ["flows_ai_builder", "flows_ai_builder_review"]


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
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        command.upgrade(cfg, "head")
        conn.close()


def _builder_tables(conn) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            """,
            (list(TABLES),),
        )
        return {name for (name,) in cursor.fetchall()}


def _columns(conn, table: str) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table,),
        )
        return {name for (name,) in cursor.fetchall()}


def _insert_role(conn, *, predefined_source: str | None) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"drop-builder-{uuid4().hex[:8]}",),
        )
        tenant_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO roles (name, permissions, predefined_source, tenant_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                predefined_source or "Custom",
                ["flows_manage", *PERMISSIONS],
                predefined_source,
                tenant_id,
            ),
        )
        return cursor.fetchone()[0]


def _permissions(conn, role_id: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        return cursor.fetchone()[0]


def test_upgrade_drops_the_tables_and_the_permissions(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    owner = _insert_role(conn, predefined_source="Owner")
    custom = _insert_role(conn, predefined_source=None)
    assert _builder_tables(conn) == TABLES

    command.upgrade(cfg, DROP_REVISION)

    assert _builder_tables(conn) == set()
    assert _permissions(conn, owner) == ["flows_manage"]
    assert _permissions(conn, custom) == ["flows_manage"]


def test_downgrade_recreates_the_tables_and_grants_owner_roles(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    command.upgrade(cfg, DROP_REVISION)
    owner = _insert_role(conn, predefined_source="Owner")
    custom = _insert_role(conn, predefined_source=None)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE roles SET permissions = ARRAY['flows_manage'] "
            "WHERE id = ANY(%s::uuid[])",
            ([owner, custom],),
        )

    command.downgrade(cfg, PRE_REVISION)

    assert {table: _columns(conn, table) for table in TABLES} == COLUMNS
    assert _permissions(conn, owner) == ["flows_manage", *PERMISSIONS]
    assert _permissions(conn, custom) == ["flows_manage"]
