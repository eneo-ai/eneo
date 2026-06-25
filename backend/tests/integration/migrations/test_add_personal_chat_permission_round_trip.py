"""Round-trip test for the add_personal_chat_permission migration.

Verifies that ``20260608_add_personal_chat`` upgrades and downgrades cleanly,
and that the permission diff is scoped exactly to roles that already grant
``assistants`` — the set that could use the personal chat before the cutover.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_add_personal_chat_permission_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "20260603_transcription_migrate"
GRANT_REVISION = "20260608_add_personal_chat"


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


class TestAddPersonalChatRoundTrip:
    def test_upgrade_grants_only_roles_with_assistants(self, round_trip_db):
        """Upgrade adds personal_chat to roles with assistants; others untouched."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)

        tenant_id = _insert_tenant(conn, "upgrade-grant")
        with_assistants_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants", "shared_spaces"],
        )
        custom_with_assistants_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Custom",
            predefined_source=None,
            permissions=["assistants"],
        )
        without_assistants_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="Insights only",
            predefined_source=None,
            permissions=["insights", "shared_spaces"],
        )

        command.upgrade(cfg, GRANT_REVISION)

        assert _get_current_revision(conn) == GRANT_REVISION
        assert "personal_chat" in _get_permissions(conn, with_assistants_id)
        assert "personal_chat" in _get_permissions(conn, custom_with_assistants_id)
        assert "personal_chat" not in _get_permissions(conn, without_assistants_id)

    def test_upgrade_is_idempotent(self, round_trip_db):
        """Re-running upgrade against an already-granted role is a no-op."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)

        tenant_id = _insert_tenant(conn, "upgrade-idempotent")
        role_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants", "personal_chat"],
        )

        command.upgrade(cfg, GRANT_REVISION)

        permissions = _get_permissions(conn, role_id)
        assert permissions.count("personal_chat") == 1, permissions

    def test_downgrade_removes_personal_chat(self, round_trip_db):
        """Downgrade strips personal_chat from every role; assistants kept."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        tenant_id = _insert_tenant(conn, "downgrade-remove")
        granted_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants", "personal_chat"],
        )

        command.downgrade(cfg, PRE_REVISION)

        assert _get_current_revision(conn) == PRE_REVISION
        permissions = _get_permissions(conn, granted_id)
        assert "personal_chat" not in permissions
        assert "assistants" in permissions

    def test_round_trip_restores_grant(self, round_trip_db):
        """upgrade → downgrade → upgrade lands personal_chat back on the role."""
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        tenant_id = _insert_tenant(conn, "round-trip")
        role_id = _insert_role(
            conn,
            tenant_id=tenant_id,
            name="User",
            predefined_source="User",
            permissions=["assistants"],
        )

        command.upgrade(cfg, GRANT_REVISION)
        assert "personal_chat" in _get_permissions(conn, role_id)

        command.downgrade(cfg, PRE_REVISION)
        assert "personal_chat" not in _get_permissions(conn, role_id)

        command.upgrade(cfg, GRANT_REVISION)
        assert "personal_chat" in _get_permissions(conn, role_id)
