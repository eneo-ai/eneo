"""Migration tests for stable service principals on service-owned API keys.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_service_principal_identity_migration.py -q
"""

from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


PRIOR_REVISION = "20260527_review_ckpt_snapshot"
MIGRATION_REVISION = "20260527_service_principals"
_TENANT_NAME_PREFIX = "service-principal-migration-"


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


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _insert_tenant_and_user(conn) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    user_id = uuid4()
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
    return tenant_id, user_id


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
                id,
                tenant_id,
                ownership,
                owner_user_id,
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
                %s,
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
                %s,
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
                %s,
                NULL,
                0
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


def _service_principal_ids_for_keys(conn, key_ids: tuple[UUID, ...]) -> list[UUID]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT service_principal_id
            FROM api_keys_v2
            WHERE id = ANY(%s)
            ORDER BY created_at, id
            """,
            (list(key_ids),),
        )
        return [row[0] for row in cur.fetchall()]


def test_upgrade_backfills_rotated_service_key_chain_to_one_principal(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id, user_id = _insert_tenant_and_user(conn)
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
    grandchild_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Service grandchild",
        rotated_from_key_id=child_key_id,
    )
    user_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="user",
        name="User key",
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    principal_ids = _service_principal_ids_for_keys(
        conn,
        (root_key_id, child_key_id, grandchild_key_id),
    )
    assert len(set(principal_ids)) == 1
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT display_name, tenant_id
            FROM service_principals
            WHERE id = %s
            """,
            (principal_ids[0],),
        )
        principal_row = cur.fetchone()
        cur.execute(
            "SELECT service_principal_id FROM api_keys_v2 WHERE id = %s",
            (user_key_id,),
        )
        user_principal_id = cur.fetchone()[0]

    assert principal_row[0] == "Service root"
    assert str(principal_row[1]) == str(tenant_id)
    assert user_principal_id is None


def test_upgrade_treats_service_key_with_non_service_parent_as_fragment_root(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id, user_id = _insert_tenant_and_user(conn)
    user_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="user",
        name="User parent",
    )
    service_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Surviving service fragment",
        rotated_from_key_id=user_key_id,
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    service_principal_id = _service_principal_ids_for_keys(conn, (service_key_id,))[0]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT service_principal_id FROM api_keys_v2 WHERE id = %s",
            (user_key_id,),
        )
        user_principal_id = cur.fetchone()[0]
        cur.execute(
            "SELECT display_name FROM service_principals WHERE id = %s",
            (service_principal_id,),
        )
        principal_name = cur.fetchone()[0]

    assert service_principal_id is not None
    assert user_principal_id is None
    assert principal_name == "Surviving service fragment"


def test_upgrade_enforces_service_principal_constraints(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id, user_id = _insert_tenant_and_user(conn)
    key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Constrained service key",
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    principal_id = _service_principal_ids_for_keys(conn, (key_id,))[0]
    with pytest.raises(psycopg2.Error):
        _insert_invalid_api_key_after_upgrade(
            conn,
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            ownership="service",
            service_principal_id=None,
        )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        _insert_invalid_api_key_after_upgrade(
            conn,
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            ownership="user",
            service_principal_id=principal_id,
        )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))
    conn.rollback()


def _insert_invalid_api_key_after_upgrade(
    conn,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID,
    ownership: str,
    service_principal_id: UUID | None,
) -> None:
    key_id = uuid4()
    owner_user_id = created_by_user_id if ownership == "user" else None
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
                permission,
                key_type,
                key_hash,
                hash_version,
                key_prefix,
                key_suffix,
                name,
                state,
                delegation_depth
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'tenant',
                'write',
                'sk_',
                %s,
                'hmac_sha256',
                'sk_',
                %s,
                'Invalid key',
                'active',
                0
            )
            """,
            (
                key_id,
                tenant_id,
                ownership,
                owner_user_id,
                service_principal_id,
                created_by_user_id,
                f"hash-{key_id}",
                str(key_id)[-8:],
            ),
        )


def test_downgrade_removes_service_principal_schema_without_deleting_keys(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    tenant_id, user_id = _insert_tenant_and_user(conn)
    key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Downgrade service key",
    )

    command.upgrade(cfg, MIGRATION_REVISION)
    command.downgrade(cfg, PRIOR_REVISION)

    assert not _table_exists(conn, "service_principals")
    assert not _column_exists(conn, "api_keys_v2", "service_principal_id")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM api_keys_v2 WHERE id = %s", (key_id,))
        assert cur.fetchone()[0] == 1
