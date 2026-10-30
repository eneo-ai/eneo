"""Round-trip flows on by default (202610220930).

The upgrade turns the ``flows_core`` flag on and gives predefined Owner and AI
Configurator roles the flow permissions new tenants receive. The downgrade
turns the flag off and leaves the permissions.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.migration_isolation

PRE_REVISION = "202610212300"
REVISION = "202610220930"
OWNER_FLOW_PERMISSIONS = {"flows_view", "flows_run", "flows_manage", "flows_trace"}


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
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_REVISION)
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        command.upgrade(cfg, "head")
        conn.close()


def _insert_role(conn, *, predefined_source: str | None, permissions: list[str]) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"flows-default-{uuid4().hex[:8]}",),
        )
        tenant_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO roles (name, permissions, predefined_source, tenant_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (predefined_source or "Custom", permissions, predefined_source, tenant_id),
        )
        return cursor.fetchone()[0]


def _permissions(conn, role_id: str) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        return cursor.fetchone()[0]


def _flag_enabled(conn) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT enabled FROM global_feature_flags WHERE name = 'flows_core'"
        )
        return cursor.fetchone()[0]


def test_upgrade_turns_flows_on_and_grants_predefined_roles(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    owner = _insert_role(
        conn, predefined_source="Owner", permissions=["assistants", "flows_view"]
    )
    configurator = _insert_role(
        conn, predefined_source="AI Configurator", permissions=["assistants"]
    )
    user = _insert_role(conn, predefined_source="User", permissions=["assistants"])
    custom = _insert_role(conn, predefined_source=None, permissions=["assistants"])
    assert not _flag_enabled(conn)

    command.upgrade(cfg, REVISION)

    assert _flag_enabled(conn)
    owner_permissions = _permissions(conn, owner)
    assert set(owner_permissions) == {"assistants", *OWNER_FLOW_PERMISSIONS}
    # A permission the role already held is not added twice.
    assert owner_permissions.count("flows_view") == 1
    assert _permissions(conn, configurator) == ["assistants", "flows_trace"]
    assert _permissions(conn, user) == ["assistants"]
    assert _permissions(conn, custom) == ["assistants"]


def test_downgrade_turns_flows_off_and_keeps_the_permissions(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    owner = _insert_role(conn, predefined_source="Owner", permissions=["assistants"])
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PRE_REVISION)

    assert not _flag_enabled(conn)
    assert set(_permissions(conn, owner)) == {"assistants", *OWNER_FLOW_PERMISSIONS}
