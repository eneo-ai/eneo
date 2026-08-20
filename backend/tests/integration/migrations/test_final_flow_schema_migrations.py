"""Migration contracts for the final two-revision core Flow schema."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = pytest.mark.migration_isolation

DEVELOP_REVISION = "202608181000"
CORE_SCHEMA_REVISION = "202608201000"
CORE_HEAD_REVISION = "202608201100"

CORE_TABLES = {
    "flow_package_imports",
    "flow_provider_calls",
    "flow_resource_bindings",
    "flow_run_audit_outbox",
    "flow_run_review_checkpoints",
    "flow_run_step_input_files",
    "flow_run_step_result_files",
    "flow_run_webhook_deliveries",
    "flow_runs",
    "flow_runtime_uploaded_files",
    "flow_step_attempt_resolved_inputs",
    "flow_step_attempts",
    "flow_step_results",
    "flow_steps",
    "flow_template_assets",
    "flow_versions",
    "flows",
    "provider_token_usages",
    "service_principals",
}
BUILDER_TABLES = {"builder_sessions", "builder_session_files", "builder_plans"}
REMOVED_PRIVATE_TABLES = {
    "flow_classification_retention_policies",
    "flow_run_rerun_invalidated_steps",
    "flow_run_rerun_operations",
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
    command.upgrade(cfg, DEVELOP_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_final_core_revision_owns_only_surviving_core_schema(migration_db) -> None:
    conn, cfg = migration_db

    assert not CORE_TABLES & _public_tables(conn)
    command.upgrade(cfg, CORE_SCHEMA_REVISION)

    tables = _public_tables(conn)
    assert CORE_TABLES <= tables
    assert not BUILDER_TABLES & tables
    assert not REMOVED_PRIVATE_TABLES & tables
    assert _column_exists(conn, "flow_step_attempts", "dispatch_task_id")
    assert not _column_exists(conn, "flow_step_attempts", "celery_task_id")
    assert not _constraint_exists(
        conn,
        "security_classifications",
        "uq_security_classifications_id_tenant_id",
    )

    command.upgrade(cfg, CORE_HEAD_REVISION)
    assert current_revisions(conn) == {CORE_HEAD_REVISION}
    assert _column_exists(conn, "api_keys_v2", "service_principal_id")
    assert _column_exists(conn, "files", "owner_service_id")
    assert _column_exists(conn, "audit_logs", "actor_api_key_id")
    assert _column_exists(conn, "completion_models", "supports_strict_tool_schema")
    assert _column_exists(conn, "tenants", "flow_settings")


def test_integration_backfills_owners_and_survives_full_round_trip(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)

    command.upgrade(cfg, CORE_HEAD_REVISION)
    first_principal_id = _assert_integration_backfill(conn, seeded)
    assert _constraint_is_validated(conn, "ck_api_keys_v2_service_principal_required")
    assert _constraint_is_validated(conn, "ck_files_owner_identity")
    assert _constraint_is_validated(
        conn, "ck_tenants_flow_run_history_retention_days_range"
    )

    command.downgrade(cfg, DEVELOP_REVISION)
    assert current_revisions(conn) == {DEVELOP_REVISION}
    assert not CORE_TABLES & _public_tables(conn)
    assert _column_exists(conn, "files", "user_id")
    assert not _column_exists(conn, "files", "owner_user_id")
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM files WHERE id = %s", (seeded["file_id"],))
        assert cur.fetchone()[0] == str(seeded["user_id"])
        cur.execute(
            "SELECT count(*) FROM api_keys_v2 WHERE id = ANY(%s)",
            (list(seeded["service_key_ids"]),),
        )
        assert cur.fetchone()[0] == 2

    command.upgrade(cfg, CORE_HEAD_REVISION)
    replayed_principal_id = _assert_integration_backfill(conn, seeded)
    assert replayed_principal_id != first_principal_id
    assert current_revisions(conn) == {CORE_HEAD_REVISION}


def test_final_constraints_reject_cross_owner_and_invalid_retention(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)
    command.upgrade(cfg, CORE_HEAD_REVISION)
    principal_id = _assert_integration_backfill(conn, seeded)

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE files SET owner_service_id = %s WHERE id = %s",
                (principal_id, seeded["file_id"]),
            )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET flow_run_history_retention_days = 0 WHERE id = %s",
                (seeded["tenant_id"],),
            )
    conn.rollback()


def _seed_develop_shaped_data(conn) -> dict[str, object]:
    tenant_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    tenant_name = f"final-flow-migration-{tenant_id}"

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
            INSERT INTO files (id, name, mimetype, file_type, user_id, tenant_id)
            VALUES (%s, 'source.pdf', 'application/pdf', 'document', %s, %s)
            """,
            (file_id, user_id, tenant_id),
        )

    root_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Service root",
    )
    child_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Service child",
        rotated_from_key_id=root_key_id,
    )
    user_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="user",
        name="User key",
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "file_id": file_id,
        "service_key_ids": (root_key_id, child_key_id),
        "user_key_id": user_key_id,
    }


def _insert_api_key(
    conn,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID,
    ownership: str,
    name: str,
    rotated_from_key_id: UUID | None = None,
) -> UUID:
    key_id = uuid4()
    owner_user_id = created_by_user_id if ownership == "user" else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO api_keys_v2 (
                id, tenant_id, ownership, owner_user_id, created_by_user_id,
                scope_type, scope_id, permission, key_type, key_hash,
                hash_version, key_prefix, key_suffix, name, state,
                rotated_from_key_id, delegation_depth
            )
            VALUES (
                %s, %s, %s, %s, %s, 'tenant', NULL, 'write', 'sk_', %s,
                'hmac_sha256', 'sk_', %s, %s, 'active', %s, 0
            )
            """,
            (
                key_id,
                tenant_id,
                ownership,
                owner_user_id,
                created_by_user_id,
                f"hash-{key_id}",
                str(key_id)[-8:],
                name,
                rotated_from_key_id,
            ),
        )
    return key_id


def _assert_integration_backfill(conn, seeded: dict[str, object]) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT owner_type, owner_user_id, owner_service_id
            FROM files
            WHERE id = %s
            """,
            (seeded["file_id"],),
        )
        assert cur.fetchone() == ("user", str(seeded["user_id"]), None)
        cur.execute(
            """
            SELECT service_principal_id
            FROM api_keys_v2
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(seeded["service_key_ids"]),),
        )
        principal_ids = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT service_principal_id FROM api_keys_v2 WHERE id = %s",
            (seeded["user_key_id"],),
        )
        assert cur.fetchone()[0] is None

    assert len(principal_ids) == 2
    assert principal_ids[0] is not None
    assert len(set(principal_ids)) == 1
    return str(principal_ids[0])


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


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
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
        return cur.fetchone()[0]


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint constraint_row
                JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
                WHERE table_row.relname = %s
                  AND constraint_row.conname = %s
            )
            """,
            (table_name, constraint_name),
        )
        return cur.fetchone()[0]


def _constraint_is_validated(conn, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT convalidated FROM pg_constraint WHERE conname = %s",
            (constraint_name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])
