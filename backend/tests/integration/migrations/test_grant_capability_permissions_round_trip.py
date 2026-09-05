"""Round-trip test for the grant_capability_permissions_to_roles migration.

``202607101006`` grants ``web_search`` and ``image_generation`` to every
existing role (predefined and custom) so nobody loses a capability that was
tenant-wide before, and the downgrade removes both from every role.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_grant_capability_permissions_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202607101005"
GRANT_REVISION = "202607101006"
CAPABILITY_PERMISSIONS = ("web_search", "image_generation")


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
    """Override shared seed_default_models — this module seeds its own data."""
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
        conn.close()


def _insert_tenant(conn, suffix: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"round-trip-{suffix}-{uuid4().hex[:8]}",),
        )
        return cur.fetchone()[0]


def _insert_role(
    conn,
    *,
    tenant_id: str,
    name: str,
    predefined_source: str | None,
    permissions: list[str],
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO roles (
                id, name, permissions, tenant_id, predefined_source,
                created_at, updated_at
            )
            VALUES (gen_random_uuid(), %s, %s, %s, %s, now(), now())
            RETURNING id
            """,
            (name, permissions, tenant_id, predefined_source),
        )
        return cur.fetchone()[0]


def _get_permissions(conn, role_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        row = cur.fetchone()
        return list(row[0]) if row else []


def _get_current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        return row[0] if row else None


def _seed_roles(conn, suffix: str) -> dict[str, str]:
    tenant_id = _insert_tenant(conn, suffix)
    return {
        "owner": _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Owner",
            predefined_source="Owner",
            permissions=["admin", "shared_spaces"],
        ),
        "user": _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants"],
        ),
        "custom": _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Custom",
            predefined_source=None,
            permissions=["assistants"],
        ),
    }


class TestGrantCapabilityPermissionsRoundTrip:
    def test_upgrade_grants_every_role(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        roles = _seed_roles(conn, "upgrade-grant")

        command.upgrade(cfg, GRANT_REVISION)

        assert _get_current_revision(conn) == GRANT_REVISION
        for role_id in roles.values():
            permissions = _get_permissions(conn, role_id)
            for permission in CAPABILITY_PERMISSIONS:
                assert permission in permissions, (role_id, permissions)

    def test_upgrade_is_idempotent(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        tenant_id = _insert_tenant(conn, "upgrade-idempotent")
        role_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Custom",
            predefined_source=None,
            permissions=["assistants", "web_search"],
        )

        command.upgrade(cfg, GRANT_REVISION)

        permissions = _get_permissions(conn, role_id)
        assert permissions.count("web_search") == 1, permissions
        assert permissions.count("image_generation") == 1, permissions

    def test_downgrade_removes_from_every_role(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        roles = _seed_roles(conn, "downgrade-remove")
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE roles
                SET permissions = permissions || %s::varchar[]
                WHERE id = ANY(%s::uuid[])
                """,
                (list(CAPABILITY_PERMISSIONS), list(roles.values())),
            )

        command.downgrade(cfg, PRE_REVISION)

        assert _get_current_revision(conn) == PRE_REVISION
        for role_id in roles.values():
            permissions = _get_permissions(conn, role_id)
            for permission in CAPABILITY_PERMISSIONS:
                assert permission not in permissions, (role_id, permissions)
            assert permissions, role_id

    def test_round_trip_restores_grants(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        roles = _seed_roles(conn, "round-trip")

        command.upgrade(cfg, GRANT_REVISION)
        command.downgrade(cfg, PRE_REVISION)
        command.upgrade(cfg, GRANT_REVISION)

        for role_id in roles.values():
            permissions = _get_permissions(conn, role_id)
            for permission in CAPABILITY_PERMISSIONS:
                assert permissions.count(permission) == 1, (role_id, permissions)
