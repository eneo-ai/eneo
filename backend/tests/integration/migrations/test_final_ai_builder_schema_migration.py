"""Migration contracts for the final stacked Flow AI Builder revision."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = pytest.mark.migration_isolation

CORE_HEAD_REVISION = "202608201100"
BUILDER_HEAD_REVISION = "202608201200"
BUILDER_TABLES = {"builder_sessions", "builder_session_files", "builder_plans"}


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

    reset_public_schema(conn)
    command.upgrade(cfg, CORE_HEAD_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_builder_revision_creates_only_final_tables_and_round_trips(
    migration_db,
) -> None:
    conn, cfg = migration_db
    fixture = _insert_core_fixture(conn)

    assert not BUILDER_TABLES & _public_tables(conn)
    assert "ai_builder" not in _constraint_definition(
        conn, "ck_flow_resource_bindings_source"
    )

    command.upgrade(cfg, BUILDER_HEAD_REVISION)
    assert current_revisions(conn) == {BUILDER_HEAD_REVISION}
    assert BUILDER_TABLES <= _public_tables(conn)
    assert "ai_builder" in _constraint_definition(
        conn, "ck_flow_resource_bindings_source"
    )
    planning_version = _column_meta(conn, "builder_sessions", "planning_state_version")
    assert planning_version[:2] == ("bigint", False)
    assert planning_version[2] is not None and "0" in planning_version[2]

    command.downgrade(cfg, CORE_HEAD_REVISION)
    assert current_revisions(conn) == {CORE_HEAD_REVISION}
    assert not BUILDER_TABLES & _public_tables(conn)
    assert "ai_builder" not in _constraint_definition(
        conn, "ck_flow_resource_bindings_source"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM files WHERE id = %s", (fixture["file_id"],))
        assert cur.fetchone()[0] == 1

    command.upgrade(cfg, BUILDER_HEAD_REVISION)
    assert current_revisions(conn) == {BUILDER_HEAD_REVISION}
    assert BUILDER_TABLES <= _public_tables(conn)


def test_builder_data_preserves_ownership_leases_and_committed_turns(
    migration_db,
) -> None:
    conn, cfg = migration_db
    fixture = _insert_core_fixture(conn)
    command.upgrade(cfg, BUILDER_HEAD_REVISION)
    builder = _insert_builder_fixture(conn, fixture)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tenant_id, actor_user_id, active_request_id, lock_token,
                   latest_turn_id, latest_turn_state, latest_turn_message_id,
                   latest_turn_error_jsonb, latest_plan_id
            FROM builder_sessions
            WHERE id = %s
            """,
            (builder["session_id"],),
        )
        session = cur.fetchone()
        cur.execute(
            """
            SELECT tenant_id, session_id, status
            FROM builder_plans
            WHERE id = %s
            """,
            (builder["plan_id"],),
        )
        plan = cur.fetchone()
        cur.execute(
            """
            SELECT tenant_id, session_id, file_id
            FROM builder_session_files
            WHERE session_id = %s AND file_id = %s
            """,
            (builder["session_id"], fixture["file_id"]),
        )
        session_file = cur.fetchone()

    assert session[:7] == (
        str(fixture["tenant_id"]),
        str(fixture["user_id"]),
        str(builder["request_id"]),
        str(builder["lock_token"]),
        str(builder["turn_id"]),
        "committed",
        str(builder["message_id"]),
    )
    assert session[7] == {"code": "provider_outcome_unknown"}
    assert session[8] == str(builder["plan_id"])
    assert plan == (
        str(fixture["tenant_id"]),
        str(builder["session_id"]),
        "proposed",
    )
    assert session_file == (
        str(fixture["tenant_id"]),
        str(builder["session_id"]),
        str(fixture["file_id"]),
    )


def test_builder_constraints_reject_cross_tenant_and_partial_commit_state(
    migration_db,
) -> None:
    conn, cfg = migration_db
    first = _insert_core_fixture(conn)
    second = _insert_core_fixture(conn)
    command.upgrade(cfg, BUILDER_HEAD_REVISION)
    builder = _insert_builder_fixture(conn, first)

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO builder_session_files (session_id, file_id, tenant_id)
                VALUES (%s, %s, %s)
                """,
                (builder["session_id"], second["file_id"], first["tenant_id"]),
            )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO builder_sessions (
                    tenant_id, space_id, target_kind, actor_user_id,
                    active_request_id
                )
                VALUES (%s, %s, 'create', %s, %s)
                """,
                (
                    first["tenant_id"],
                    first["space_id"],
                    first["user_id"],
                    uuid4(),
                ),
            )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE builder_sessions
                SET latest_turn_state = 'open'
                WHERE id = %s
                """,
                (builder["session_id"],),
            )
    conn.rollback()


def _insert_core_fixture(conn) -> dict[str, UUID]:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    file_id = uuid4()
    tenant_name = f"final-builder-migration-{tenant_id}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id, name, display_name, slug, quota_limit, privacy_policy,
                domain, zitadel_org_id, provisioning, security_enabled, state
            )
            VALUES (%s, %s, %s, %s, 100000, NULL, NULL, NULL, false, false, 'active')
            """,
            (tenant_id, tenant_name, tenant_name, tenant_name[:63]),
        )
        cur.execute(
            """
            INSERT INTO users (
                id, username, email, email_verified, salt, password, is_active,
                state, used_tokens, tenant_id, quota_limit
            )
            VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
            """,
            (user_id, f"user-{user_id}", f"{user_id}@example.test", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO spaces (id, name, description, tenant_id, user_id)
            VALUES (%s, 'Builder migration space', NULL, %s, NULL)
            """,
            (space_id, tenant_id),
        )
        cur.execute(
            """
            INSERT INTO files (
                id, name, mimetype, file_type, owner_type, owner_user_id,
                owner_service_id, tenant_id
            )
            VALUES (
                %s, 'builder-source.pdf', 'application/pdf', 'document',
                'user', %s, NULL, %s
            )
            """,
            (file_id, user_id, tenant_id),
        )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "space_id": space_id,
        "file_id": file_id,
    }


def _insert_builder_fixture(
    conn,
    core: dict[str, UUID],
) -> dict[str, UUID]:
    session_id = uuid4()
    plan_id = uuid4()
    request_id = uuid4()
    lock_token = uuid4()
    turn_id = uuid4()
    message_id = uuid4()
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO builder_sessions (
                id, tenant_id, space_id, target_kind, actor_user_id,
                conversation, active_request_id, lock_token, locked_at,
                lock_expires_at, latest_turn_id,
                latest_turn_request_fingerprint, latest_turn_request_jsonb,
                latest_turn_state, latest_turn_message_id,
                latest_turn_error_jsonb
            )
            VALUES (
                %s, %s, %s, 'create', %s, '[]'::jsonb, %s, %s, %s, %s,
                %s, %s, %s, 'committed', %s, %s
            )
            """,
            (
                session_id,
                core["tenant_id"],
                core["space_id"],
                core["user_id"],
                request_id,
                lock_token,
                now,
                now + timedelta(minutes=5),
                turn_id,
                "a" * 64,
                Json({"message": "Build a flow"}),
                message_id,
                Json({"code": "provider_outcome_unknown"}),
            ),
        )
        cur.execute(
            """
            INSERT INTO builder_plans (
                id, session_id, tenant_id, status, proposal_json, spec_hash
            )
            VALUES (%s, %s, %s, 'proposed', %s, %s)
            """,
            (
                plan_id,
                session_id,
                core["tenant_id"],
                Json({"steps": []}),
                "b" * 64,
            ),
        )
        cur.execute(
            "UPDATE builder_sessions SET latest_plan_id = %s WHERE id = %s",
            (plan_id, session_id),
        )
        cur.execute(
            """
            INSERT INTO builder_session_files (session_id, file_id, tenant_id)
            VALUES (%s, %s, %s)
            """,
            (session_id, core["file_id"], core["tenant_id"]),
        )
    return {
        "session_id": session_id,
        "plan_id": plan_id,
        "request_id": request_id,
        "lock_token": lock_token,
        "turn_id": turn_id,
        "message_id": message_id,
    }


def _public_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
        return {row[0] for row in cur.fetchall()}


def _constraint_definition(conn, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (name,),
        )
        row = cur.fetchone()
    assert row is not None
    return str(row[0])


def _column_meta(
    conn,
    table_name: str,
    column_name: str,
) -> tuple[str, bool, str | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        row = cur.fetchone()
    assert row is not None
    default = str(row[2]) if row[2] is not None else None
    return str(row[0]), row[1] == "YES", default
