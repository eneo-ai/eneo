"""Migration tests for deleting Flow legacy user id mirrors.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_legacy_user_id_mirrors_removed.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


PRIOR_REVISION = "20260526_flow_published_fk"
MIGRATION_REVISION = "20260526_flow_user_mirror_drop"
_TENANT_NAME_PREFIX = "flow-user-mirror-migration-"


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


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    return row[0] if row else None


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


def _fk_delete_rule(conn, table_name: str, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT confdeltype
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _insert_user_owned_fixture(conn) -> dict[str, str]:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    flow_run_id = uuid4()
    file_id = uuid4()
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
            (space_id, "Flow user mirror migration space", tenant_id),
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
                "Flow user mirror migration flow",
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
            VALUES (%s, 1, %s, 'checksum-user-mirror', %s)
            """,
            (
                flow_id,
                tenant_id,
                Json(
                    {
                        "schema_version": 1,
                        "flow_id": str(flow_id),
                        "name": "Flow user mirror migration flow",
                        "steps": [],
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
            INSERT INTO files (
                id,
                name,
                text,
                blob,
                checksum,
                size,
                mimetype,
                file_type,
                transcription,
                owner_type,
                owner_user_id,
                owner_api_key_id,
                user_id,
                tenant_id
            )
            VALUES (%s, 'source.pdf', 'text', NULL, 'checksum-file', 12, 'application/pdf', 'document', NULL, 'user', %s, NULL, %s, %s)
            """,
            (file_id, user_id, user_id, tenant_id),
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
                user_id,
                tenant_id,
                trace_id,
                status,
                input_payload_json
            )
            VALUES (%s, %s, 1, 'user', %s, NULL, %s, %s, %s, 'completed', '{}')
            """,
            (flow_run_id, flow_id, user_id, user_id, tenant_id, uuid4()),
        )

    return {
        "file_id": str(file_id),
        "flow_run_id": str(flow_run_id),
        "user_id": str(user_id),
    }


def _insert_service_key_owned_fixture(conn) -> dict[str, str]:
    tenant_id = uuid4()
    user_id = uuid4()
    api_key_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    flow_run_id = uuid4()
    file_id = uuid4()
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
            INSERT INTO api_keys_v2 (
                id,
                tenant_id,
                ownership,
                owner_user_id,
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
                resource_permissions,
                state,
                created_by_user_id
            )
            VALUES (
                %s,
                %s,
                'service_key',
                %s,
                'tenant',
                NULL,
                'read_write',
                'api_key',
                %s,
                'v1',
                'test',
                'test',
                'Flow migration service key',
                NULL,
                NULL,
                'active',
                %s
            )
            """,
            (
                api_key_id,
                tenant_id,
                user_id,
                f"hash-{api_key_id}",
                user_id,
            ),
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
            (space_id, "Flow service-key migration space", tenant_id),
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
                "Flow service-key migration flow",
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
            VALUES (%s, 1, %s, 'checksum-service-key-mirror', %s)
            """,
            (
                flow_id,
                tenant_id,
                Json(
                    {
                        "schema_version": 1,
                        "flow_id": str(flow_id),
                        "name": "Flow service-key migration flow",
                        "steps": [],
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
            INSERT INTO files (
                id,
                name,
                text,
                blob,
                checksum,
                size,
                mimetype,
                file_type,
                transcription,
                owner_type,
                owner_user_id,
                owner_api_key_id,
                user_id,
                tenant_id
            )
            VALUES (%s, 'service-key-source.pdf', 'text', NULL, 'checksum-service-key-file', 12, 'application/pdf', 'document', NULL, 'service_key', NULL, %s, NULL, %s)
            """,
            (file_id, api_key_id, tenant_id),
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
                user_id,
                tenant_id,
                trace_id,
                status,
                input_payload_json
            )
            VALUES (%s, %s, 1, 'service_key', NULL, %s, NULL, %s, %s, 'completed', '{}')
            """,
            (flow_run_id, flow_id, api_key_id, tenant_id, uuid4()),
        )

    return {
        "file_id": str(file_id),
        "flow_run_id": str(flow_run_id),
        "user_id": str(user_id),
    }


def _legacy_user_values(conn, ids: dict[str, str]) -> tuple[str | None, str | None]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id::text FROM files WHERE id = %s",
            (ids["file_id"],),
        )
        file_user_id = cur.fetchone()[0]
        cur.execute(
            "SELECT user_id::text FROM flow_runs WHERE id = %s",
            (ids["flow_run_id"],),
        )
        run_user_id = cur.fetchone()[0]
    return file_user_id, run_user_id


def test_upgrade_drops_legacy_mirrors_and_downgrade_rebuilds_them(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    user_ids = _insert_user_owned_fixture(conn)
    service_key_ids = _insert_service_key_owned_fixture(conn)

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _column_exists(conn, "files", "user_id") is False
    assert _column_exists(conn, "flow_runs", "user_id") is False

    command.downgrade(cfg, PRIOR_REVISION)

    assert _column_exists(conn, "files", "user_id") is True
    assert _column_exists(conn, "flow_runs", "user_id") is True
    assert _legacy_user_values(conn, user_ids) == (
        user_ids["user_id"],
        user_ids["user_id"],
    )
    assert _legacy_user_values(conn, service_key_ids) == (None, None)
    assert _fk_delete_rule(conn, "files", "files_users_fkey") == "n"
    assert _fk_delete_rule(conn, "flow_runs", "flow_runs_user_id_fkey") == "n"

    command.upgrade(cfg, MIGRATION_REVISION)
    assert _column_exists(conn, "files", "user_id") is False
    assert _column_exists(conn, "flow_runs", "user_id") is False


def test_upgrade_aborts_when_legacy_mirrors_disagree_with_typed_identity(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    ids = _insert_user_owned_fixture(conn)

    with conn.cursor() as cur:
        cur.execute("UPDATE files SET user_id = NULL WHERE id = %s", (ids["file_id"],))

    with pytest.raises(Exception) as exc_info:
        command.upgrade(cfg, MIGRATION_REVISION)

    assert "Cannot drop files.user_id" in str(exc_info.value)
    assert _current_revision(conn) == PRIOR_REVISION
    assert _column_exists(conn, "files", "user_id") is True
    assert _column_exists(conn, "flow_runs", "user_id") is True


def test_upgrade_aborts_when_service_key_file_uses_legacy_user_mirror(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    ids = _insert_service_key_owned_fixture(conn)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE files SET user_id = %s WHERE id = %s",
            (ids["user_id"], ids["file_id"]),
        )

    with pytest.raises(Exception) as exc_info:
        command.upgrade(cfg, MIGRATION_REVISION)

    assert "Cannot drop files.user_id" in str(exc_info.value)
    assert _current_revision(conn) == PRIOR_REVISION
    assert _column_exists(conn, "files", "user_id") is True
    assert _column_exists(conn, "flow_runs", "user_id") is True


def test_upgrade_aborts_when_service_key_run_uses_legacy_user_mirror(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    ids = _insert_service_key_owned_fixture(conn)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET user_id = %s WHERE id = %s",
            (ids["user_id"], ids["flow_run_id"]),
        )

    with pytest.raises(Exception) as exc_info:
        command.upgrade(cfg, MIGRATION_REVISION)

    assert "Cannot drop flow_runs.user_id" in str(exc_info.value)
    assert _current_revision(conn) == PRIOR_REVISION
    assert _column_exists(conn, "files", "user_id") is True
    assert _column_exists(conn, "flow_runs", "user_id") is True
