"""Round trip of the migration that gives admin keys the administration permission.

Before it, any organization-scoped secret key whose highest resource
permission was admin reached the organization's administration. The upgrade
writes that down as a permission of its own on exactly those keys; the
downgrade takes the permission off every key, because the earlier code refuses
permissions it does not know.

Run alongside other migration round trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_grant_administration_to_admin_keys_round_trip.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.migration_isolation]

PRE_REVISION = "202611201305"
GRANT_REVISION = "202611271000"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override shared cleanup_database so schema revisions persist across
    downgrade/upgrade cycles within this module.
    """
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override shared seed_default_models: this module seeds its own data."""
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

    command.upgrade(cfg, GRANT_REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        command.upgrade(cfg, GRANT_REVISION)
        conn.close()


def _insert_tenant(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"administration-round-trip-{uuid4().hex[:8]}",),
        )
        return cur.fetchone()[0]


def _insert_key(
    conn,
    *,
    tenant_id: str,
    key_type: str = "sk_",
    scope_type: str = "tenant",
    permission: str,
    resource_permissions: dict[str, str] | None,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO api_keys_v2 (
                id, tenant_id, ownership, scope_type, scope_id, permission,
                key_type, key_hash, hash_version, key_prefix, key_suffix, name,
                resource_permissions, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), %s, 'service', %s, %s, %s,
                %s, %s, 'hmac_sha256', %s, 'abcd', 'round trip',
                %s, now(), now()
            )
            RETURNING id
            """,
            (
                tenant_id,
                scope_type,
                None if scope_type == "tenant" else str(uuid4()),
                permission,
                key_type,
                uuid4().hex,
                key_type,
                None
                if resource_permissions is None
                else json.dumps(resource_permissions),
            ),
        )
        return cur.fetchone()[0]


def _resource_permissions(conn, key_id: str) -> dict[str, str] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_permissions FROM api_keys_v2 WHERE id = %s", (key_id,)
        )
        return cur.fetchone()[0]


def test_upgrade_gives_it_to_the_keys_that_reached_the_administration(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    command.downgrade(cfg, PRE_REVISION)
    tenant_id = _insert_tenant(conn)
    one_admin_row = {"assistants": "read", "prompts": "admin"}

    reached = _insert_key(
        conn,
        tenant_id=tenant_id,
        permission="admin",
        resource_permissions=one_admin_row,
    )
    below_admin = _insert_key(
        conn,
        tenant_id=tenant_id,
        permission="write",
        resource_permissions={"assistants": "write"},
    )
    one_space = _insert_key(
        conn,
        tenant_id=tenant_id,
        scope_type="space",
        permission="admin",
        resource_permissions=one_admin_row,
    )
    without_resource_permissions = _insert_key(
        conn, tenant_id=tenant_id, permission="admin", resource_permissions=None
    )
    public = _insert_key(
        conn,
        tenant_id=tenant_id,
        key_type="pk_",
        permission="read",
        resource_permissions={"assistants": "read"},
    )

    command.upgrade(cfg, GRANT_REVISION)

    assert _resource_permissions(conn, reached) == {
        **one_admin_row,
        "administration": "admin",
    }
    assert _resource_permissions(conn, below_admin) == {"assistants": "write"}
    assert _resource_permissions(conn, one_space) == one_admin_row
    # Left to the rule for keys without per-resource permissions.
    assert _resource_permissions(conn, without_resource_permissions) is None
    assert _resource_permissions(conn, public) == {"assistants": "read"}


def test_downgrade_takes_it_off_every_key(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    tenant_id = _insert_tenant(conn)
    given_later = _insert_key(
        conn,
        tenant_id=tenant_id,
        permission="read",
        resource_permissions={"assistants": "read", "administration": "write"},
    )

    command.downgrade(cfg, PRE_REVISION)

    assert _resource_permissions(conn, given_later) == {"assistants": "read"}
