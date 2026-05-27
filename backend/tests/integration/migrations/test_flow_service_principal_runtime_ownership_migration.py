"""Migration tests for stable service-principal Flow runtime ownership.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_service_principal_runtime_ownership_migration.py -q
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import Json
from sqlalchemy.exc import InternalError

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260527_service_principals"
MIGRATION_REVISION = "20260527_flow_sp_runtime_owner"
_TENANT_NAME_PREFIX = "flow-service-principal-owner-migration-"


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
    _clear_seeded_rows(conn)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _clear_seeded_rows(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tenants WHERE name LIKE %s",
            (_TENANT_NAME_PREFIX + "%",),
        )


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        return cur.fetchone() is not None


def _index_exists(conn, index_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (index_name,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _insert_runtime_fixture(conn) -> dict[str, UUID]:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    flow_run_id = uuid4()
    service_principal_id = uuid4()
    api_key_id = uuid4()
    file_id = uuid4()
    checkpoint_id = uuid4()
    rerun_operation_id = uuid4()
    step_id = uuid4()
    tenant_name = f"{_TENANT_NAME_PREFIX}{tenant_id}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id,
                name,
                display_name,
                slug,
                quota_limit,
                privacy_policy,
                domain,
                zitadel_org_id,
                provisioning,
                security_enabled,
                state
            )
            VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, false, false, 'active')
            """,
            (tenant_id, tenant_name, tenant_name, tenant_name[:63], 100000),
        )
        cur.execute(
            """
            INSERT INTO users (
                id,
                username,
                email,
                email_verified,
                salt,
                password,
                is_active,
                state,
                used_tokens,
                tenant_id,
                quota_limit
            )
            VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
            """,
            (user_id, f"user-{user_id}", f"{user_id}@example.test", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO spaces (
                id,
                name,
                description,
                data_retention_days,
                tenant_id,
                user_id
            )
            VALUES (%s, %s, NULL, NULL, %s, NULL)
            """,
            (space_id, "Runtime owner migration space", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO service_principals (
                id,
                tenant_id,
                display_name,
                description,
                scope_type,
                scope_id,
                state,
                created_by_user_id,
                disabled_at
            )
            VALUES (%s, %s, %s, NULL, 'tenant', NULL, 'active', %s, NULL)
            """,
            (service_principal_id, tenant_id, "Runtime service", user_id),
        )
        cur.execute(
            """
            INSERT INTO api_keys_v2 (
                id,
                tenant_id,
                ownership,
                owner_user_id,
                service_principal_id,
                created_by_user_id,
                scope_type,
                scope_id,
                permission,
                key_type,
                key_hash,
                hash_version,
                key_prefix,
                key_suffix,
                name,
                description,
                allowed_origins,
                allowed_ips,
                resource_permissions,
                state,
                expires_at,
                last_used_at,
                revoked_at,
                revoked_reason_code,
                revoked_reason_text,
                suspended_at,
                suspended_reason_code,
                suspended_reason_text,
                rotation_grace_until,
                rotated_from_key_id,
                created_by_key_id,
                delegation_depth
            )
            VALUES (
                %s,
                %s,
                'service',
                NULL,
                %s,
                %s,
                'tenant',
                NULL,
                'write',
                'sk_',
                %s,
                'hmac_sha256',
                'sk_',
                %s,
                'Runtime key',
                NULL,
                NULL,
                NULL,
                NULL,
                'active',
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                0
            )
            """,
            (
                api_key_id,
                tenant_id,
                service_principal_id,
                user_id,
                f"hash-{api_key_id}",
                str(api_key_id)[-8:],
            ),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id,
                name,
                description,
                tenant_id,
                space_id,
                created_by_user_id,
                owner_user_id,
                published_version,
                metadata_json,
                data_retention_days
            )
            VALUES (%s, %s, NULL, %s, %s, %s, %s, NULL, NULL, NULL)
            """,
            (
                flow_id,
                "Runtime owner migration flow",
                tenant_id,
                space_id,
                user_id,
                user_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_versions (
                flow_id,
                version,
                tenant_id,
                definition_checksum,
                definition_json
            )
            VALUES (%s, 1, %s, %s, %s)
            """,
            (
                flow_id,
                tenant_id,
                "definition-checksum",
                Json(
                    {
                        "schema_version": 1,
                        "flow_id": str(flow_id),
                        "steps": [
                            {
                                "step_id": str(step_id),
                                "step_order": 1,
                                "assistant_id": str(uuid4()),
                                "input_source": "flow_input",
                                "input_type": "text",
                                "output_mode": "pass_through",
                                "output_type": "json",
                                "mcp_policy": "inherit",
                            }
                        ],
                    }
                ),
            ),
        )
        cur.execute(
            "UPDATE flows SET published_version = 1 WHERE id = %s",
            (flow_id,),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                principal_api_key_id,
                tenant_id,
                trace_id,
                idempotency_key,
                request_fingerprint,
                revision,
                status,
                input_payload_json
            )
            VALUES (
                %s,
                %s,
                1,
                'service_key',
                NULL,
                %s,
                %s,
                %s,
                'idem-key',
                'request-fingerprint',
                1,
                'awaiting_review',
                %s
            )
            """,
            (
                flow_run_id,
                flow_id,
                api_key_id,
                tenant_id,
                uuid4(),
                Json({"case_id": "123"}),
            ),
        )
        cur.execute(
            """
            INSERT INTO files (
                id,
                name,
                checksum,
                size,
                mimetype,
                file_type,
                text,
                blob,
                transcription,
                owner_type,
                owner_user_id,
                owner_api_key_id,
                tenant_id
            )
            VALUES (
                %s,
                'input.txt',
                'checksum',
                11,
                'text/plain',
                'text',
                'hello world',
                NULL,
                NULL,
                'service_key',
                NULL,
                %s,
                %s
            )
            """,
            (file_id, api_key_id, tenant_id),
        )
        cur.execute(
            """
            INSERT INTO flow_run_review_checkpoints (
                id,
                tenant_id,
                flow_id,
                flow_run_id,
                step_id,
                step_order,
                attempt_no,
                state,
                revision,
                schema_version,
                original_payload_json,
                current_payload_json,
                step_label,
                review_mode,
                output_type,
                requester_user_id,
                requester_principal_type,
                decided_by_user_id,
                decided_by_principal_type,
                next_step_ids_json
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                1,
                1,
                'approved',
                1,
                1,
                %s,
                %s,
                'Review step',
                'edit',
                'json',
                NULL,
                'service_key',
                NULL,
                'service_key',
                %s
            )
            """,
            (
                checkpoint_id,
                tenant_id,
                flow_id,
                flow_run_id,
                step_id,
                Json({"text": "draft"}),
                Json({"text": "approved"}),
                Json([]),
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_run_rerun_operations (
                id,
                tenant_id,
                flow_id,
                flow_run_id,
                rerun_step_id,
                rerun_step_order,
                root_attempt_no,
                root_attempt_id,
                status,
                request_fingerprint,
                expected_run_revision,
                accepted_run_revision,
                reason,
                input_payload_json,
                step_inputs_json,
                requested_by_principal_type,
                requested_by_user_id
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                1,
                1,
                NULL,
                'queued',
                'rerun-fingerprint',
                1,
                1,
                'User requested rerun',
                NULL,
                NULL,
                'user',
                %s
            )
            """,
            (rerun_operation_id, tenant_id, flow_id, flow_run_id, step_id, user_id),
        )

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "flow_id": flow_id,
        "flow_run_id": flow_run_id,
        "service_principal_id": service_principal_id,
        "api_key_id": api_key_id,
        "file_id": file_id,
        "checkpoint_id": checkpoint_id,
        "rerun_operation_id": rerun_operation_id,
    }


def _insert_service_idempotency_collision(conn, ids: dict[str, UUID]) -> None:
    second_api_key_id = uuid4()
    second_run_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO api_keys_v2 (
                id,
                tenant_id,
                ownership,
                owner_user_id,
                service_principal_id,
                created_by_user_id,
                scope_type,
                scope_id,
                permission,
                key_type,
                key_hash,
                hash_version,
                key_prefix,
                key_suffix,
                name,
                description,
                allowed_origins,
                allowed_ips,
                resource_permissions,
                state,
                expires_at,
                last_used_at,
                revoked_at,
                revoked_reason_code,
                revoked_reason_text,
                suspended_at,
                suspended_reason_code,
                suspended_reason_text,
                rotation_grace_until,
                rotated_from_key_id,
                created_by_key_id,
                delegation_depth
            )
            VALUES (
                %s,
                %s,
                'service',
                NULL,
                %s,
                %s,
                'tenant',
                NULL,
                'write',
                'sk_',
                %s,
                'hmac_sha256',
                'sk_',
                %s,
                'Runtime key collision',
                NULL,
                NULL,
                NULL,
                NULL,
                'active',
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                0
            )
            """,
            (
                second_api_key_id,
                ids["tenant_id"],
                ids["service_principal_id"],
                ids["user_id"],
                f"hash-{second_api_key_id}",
                str(second_api_key_id)[-8:],
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                id,
                flow_id,
                flow_version,
                principal_type,
                principal_user_id,
                principal_api_key_id,
                tenant_id,
                trace_id,
                idempotency_key,
                request_fingerprint,
                revision,
                status,
                input_payload_json
            )
            VALUES (
                %s,
                %s,
                1,
                'service_key',
                NULL,
                %s,
                %s,
                %s,
                'idem-key',
                'collision-fingerprint',
                1,
                'queued',
                %s
            )
            """,
            (
                second_run_id,
                ids["flow_id"],
                second_api_key_id,
                ids["tenant_id"],
                uuid4(),
                Json({"case_id": "collision"}),
            ),
        )


def test_upgrade_moves_flow_file_review_ownership_to_service_principals(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    ids = _insert_runtime_fixture(conn)

    command.upgrade(cfg, MIGRATION_REVISION)

    assert not _column_exists(conn, "flow_runs", "principal_api_key_id")
    assert not _column_exists(conn, "files", "owner_api_key_id")
    assert _constraint_exists(conn, "flow_runs", "ck_flow_runs_principal_identity")
    assert _constraint_exists(conn, "files", "ck_files_owner_identity")
    assert _constraint_exists(
        conn,
        "flow_run_review_checkpoints",
        "ck_flow_run_review_checkpoints_requester_principal",
    )
    assert _constraint_exists(
        conn,
        "flow_run_review_checkpoints",
        "ck_flow_run_review_checkpoints_decider_principal",
    )
    assert _constraint_exists(
        conn,
        "flow_run_rerun_operations",
        "ck_flow_run_rerun_operations_requester_principal",
    )
    assert _index_exists(conn, "uq_flow_runs_idempotency_service_key")
    assert _index_exists(conn, "ix_flow_runs_service_principal_created_at")
    assert _index_exists(conn, "ix_files_service_owner_created_at")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT principal_service_id, created_by_api_key_id, runtime_service_permission
            FROM flow_runs
            WHERE id = %s
            """,
            (ids["flow_run_id"],),
        )
        assert cur.fetchone() == (
            str(ids["service_principal_id"]),
            str(ids["api_key_id"]),
            "write",
        )
        cur.execute(
            """
            SELECT owner_service_id
            FROM files
            WHERE id = %s
            """,
            (ids["file_id"],),
        )
        assert cur.fetchone() == (str(ids["service_principal_id"]),)
        cur.execute(
            """
            SELECT requester_service_id, decided_by_service_id
            FROM flow_run_review_checkpoints
            WHERE id = %s
            """,
            (ids["checkpoint_id"],),
        )
        assert cur.fetchone() == (
            str(ids["service_principal_id"]),
            str(ids["service_principal_id"]),
        )
        cur.execute(
            """
            SELECT requested_by_user_id IS NOT NULL, requested_by_service_id
            FROM flow_run_rerun_operations
            WHERE id = %s
            """,
            (ids["rerun_operation_id"],),
        )
        assert cur.fetchone() == (True, None)


def test_downgrade_refuses_while_service_principal_flow_data_exists(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    _insert_runtime_fixture(conn)

    command.upgrade(cfg, MIGRATION_REVISION)

    with pytest.raises(
        InternalError,
        match="Downgrade from service-principal Flow ownership is unsupported",
    ):
        command.downgrade(cfg, PRIOR_REVISION)


def test_upgrade_rejects_service_principal_idempotency_collision(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    ids = _insert_runtime_fixture(conn)
    _insert_service_idempotency_collision(conn, ids)

    with pytest.raises(InternalError, match="idempotency key collisions"):
        command.upgrade(cfg, MIGRATION_REVISION)
