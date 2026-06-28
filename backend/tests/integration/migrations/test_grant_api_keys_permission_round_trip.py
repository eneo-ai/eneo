"""Round-trip test for the grant_api_keys_permission_to_owner migration.

Verifies that ``202604281200_grant_api_keys_permission_to_owner`` upgrades
and downgrades cleanly, and that the permission diff is scoped exactly to
roles whose ``predefined_source = 'Owner'``.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_grant_api_keys_permission_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202604231400"
GRANT_REVISION = "202604281200"


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


class TestGrantApiKeysRoundTrip:
    def test_upgrade_grants_only_owner_roles(self, round_trip_db):
        """Upgrade adds api_keys to Owner roles and leaves siblings alone."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)

        tenant_id = _insert_tenant(conn, "upgrade-grant")
        owner_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Owner",
            predefined_source="Owner",
            permissions=["admin", "shared_spaces"],
        )
        ai_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="AI Configurator",
            predefined_source="AI Configurator",
            permissions=["assistants"],
        )
        user_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants"],
        )
        custom_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Custom",
            predefined_source=None,
            permissions=["assistants"],
        )

        command.upgrade(cfg, GRANT_REVISION)

        assert _get_current_revision(conn) == GRANT_REVISION
        assert "api_keys" in _get_permissions(conn, owner_id)
        assert "api_keys" not in _get_permissions(conn, ai_id)
        assert "api_keys" not in _get_permissions(conn, user_id)
        assert "api_keys" not in _get_permissions(conn, custom_id)

    def test_upgrade_is_idempotent(self, round_trip_db):
        """Re-running upgrade against an already-granted Owner role is a no-op."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)

        tenant_id = _insert_tenant(conn, "upgrade-idempotent")
        owner_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Owner",
            predefined_source="Owner",
            permissions=["admin", "api_keys"],
        )

        command.upgrade(cfg, GRANT_REVISION)

        permissions = _get_permissions(conn, owner_id)
        assert permissions.count("api_keys") == 1, permissions

    def test_downgrade_removes_api_keys_only_from_owner(self, round_trip_db):
        """Downgrade strips api_keys from Owner; siblings keep their values."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        tenant_id = _insert_tenant(conn, "downgrade-remove")
        owner_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Owner",
            predefined_source="Owner",
            permissions=["admin", "api_keys"],
        )
        ai_with_grant_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="AI Configurator",
            predefined_source="AI Configurator",
            permissions=["assistants", "api_keys"],
        )
        custom_with_grant_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Custom",
            predefined_source=None,
            permissions=["api_keys"],
        )

        command.downgrade(cfg, PRE_REVISION)

        assert _get_current_revision(conn) == PRE_REVISION
        assert "api_keys" not in _get_permissions(conn, owner_id)
        assert "api_keys" in _get_permissions(conn, ai_with_grant_id)
        assert "api_keys" in _get_permissions(conn, custom_with_grant_id)

    def test_round_trip_restores_grant_on_owner(self, round_trip_db):
        """upgrade → downgrade → upgrade lands api_keys back on Owner roles."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        tenant_id = _insert_tenant(conn, "round-trip")
        owner_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Owner",
            predefined_source="Owner",
            permissions=["admin"],
        )

        command.upgrade(cfg, GRANT_REVISION)
        assert "api_keys" in _get_permissions(conn, owner_id)

        command.downgrade(cfg, PRE_REVISION)
        assert "api_keys" not in _get_permissions(conn, owner_id)

        command.upgrade(cfg, GRANT_REVISION)
        assert "api_keys" in _get_permissions(conn, owner_id)
