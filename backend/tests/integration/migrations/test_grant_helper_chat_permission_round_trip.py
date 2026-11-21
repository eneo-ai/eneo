"""Round-trip the helper chat permission grant migration."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611182000"
GRANT_REVISION = "202611201200"


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
            (f"helper-chat-grant-{suffix}-{uuid4().hex[:8]}",),
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


def test_the_grant_reaches_the_owner_role_once_and_the_downgrade_takes_it_back(
    round_trip_db,
):
    conn = round_trip_db["conn"]
    cfg = round_trip_db["cfg"]
    command.downgrade(cfg, PRE_REVISION)
    tenant_id = _insert_tenant(conn, "grant")
    roles = {
        source: _insert_role(
            conn,
            tenant_id=tenant_id,
            predefined_source=source,
            permissions=["assistants"],
        )
        for source in ("Owner", "AI Configurator", "User", None)
    }
    already = _insert_role(
        conn,
        tenant_id=_insert_tenant(conn, "granted"),
        predefined_source="Owner",
        permissions=["admin", "helper_chat"],
    )

    command.upgrade(cfg, GRANT_REVISION)

    granted = {
        source
        for source, id in roles.items()
        if "helper_chat" in _permissions(conn, id)
    }
    assert granted == {"Owner"}
    assert _permissions(conn, already).count("helper_chat") == 1

    command.downgrade(cfg, PRE_REVISION)

    # A grant an administrator made by hand goes too: the value is no longer known.
    assert _permissions(conn, roles["Owner"]) == ["assistants"]
    assert _permissions(conn, already) == ["admin"]
