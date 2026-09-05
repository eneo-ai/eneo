"""Round-trip the flows_ai_builder_review grant migration (202609052200).

Reviewing a published flow's runs with the AI Builder is a feature an
organisation grants per role. The migration converges existing Owner rows
only; AI Configurator, User and custom roles stay as the administrator left
them, so delegation is always explicit.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202609041000"
GRANT_REVISION = "202609052200"
PERMISSION = "flows_ai_builder_review"


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
    command.upgrade(cfg, GRANT_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _insert_tenant(conn, suffix: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"ai-builder-review-{suffix}-{uuid4().hex[:8]}",),
        )
        return cursor.fetchone()[0]


def _insert_role(
    conn,
    *,
    tenant_id: str,
    predefined_source: str | None,
    permissions: list[str],
) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO roles (
                id, name, permissions, tenant_id, predefined_source,
                created_at, updated_at
            )
            VALUES (gen_random_uuid(), %s, %s, %s, %s, now(), now())
            RETURNING id
            """,
            (predefined_source or "Custom", permissions, tenant_id, predefined_source),
        )
        return cursor.fetchone()[0]


def _permissions(conn, role_id: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        return list(cursor.fetchone()[0])


def test_upgrade_grants_existing_owner_rows_only(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    command.downgrade(cfg, PRE_REVISION)

    tenant_id = _insert_tenant(conn, "upgrade")
    owner_id = _insert_role(
        conn, tenant_id=tenant_id, predefined_source="Owner", permissions=["admin"]
    )
    configurator_id = _insert_role(
        conn,
        tenant_id=tenant_id,
        predefined_source="AI Configurator",
        permissions=["flows_trace"],
    )
    user_id = _insert_role(
        conn, tenant_id=tenant_id, predefined_source="User", permissions=["assistants"]
    )
    custom_id = _insert_role(
        conn,
        tenant_id=tenant_id,
        predefined_source=None,
        permissions=["flows_manage", "flows_ai_builder"],
    )

    command.upgrade(cfg, GRANT_REVISION)

    assert PERMISSION in _permissions(conn, owner_id)
    assert "admin" in _permissions(conn, owner_id)
    assert PERMISSION not in _permissions(conn, configurator_id)
    assert PERMISSION not in _permissions(conn, user_id)
    assert PERMISSION not in _permissions(conn, custom_id)


def test_upgrade_is_idempotent_for_an_already_granted_owner(round_trip_db):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    command.downgrade(cfg, PRE_REVISION)
    tenant_id = _insert_tenant(conn, "idempotent")
    owner_id = _insert_role(
        conn,
        tenant_id=tenant_id,
        predefined_source="Owner",
        permissions=["admin", PERMISSION],
    )

    command.upgrade(cfg, GRANT_REVISION)
    command.downgrade(cfg, PRE_REVISION)
    command.upgrade(cfg, GRANT_REVISION)

    assert _permissions(conn, owner_id).count(PERMISSION) == 1


def test_downgrade_removes_the_grant_from_owner_rows_and_leaves_custom_roles(
    round_trip_db,
):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    tenant_id = _insert_tenant(conn, "downgrade")
    owner_id = _insert_role(
        conn,
        tenant_id=tenant_id,
        predefined_source="Owner",
        permissions=["admin", PERMISSION],
    )
    custom_id = _insert_role(
        conn, tenant_id=tenant_id, predefined_source=None, permissions=[PERMISSION]
    )

    command.downgrade(cfg, PRE_REVISION)

    assert PERMISSION not in _permissions(conn, owner_id)
    assert "admin" in _permissions(conn, owner_id)
    # A grant an administrator made by hand is theirs; the migration only
    # converges what it added.
    assert PERMISSION in _permissions(conn, custom_id)
