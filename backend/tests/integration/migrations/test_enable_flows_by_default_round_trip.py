"""Round-trip 202610220930, which leaves Flows as the organisation chose them.

Neither direction touches the ``flows_core`` flag or any role: an upgrade does
not switch Flows on or grant flow permissions, and a downgrade does not undo a
choice an administrator made.
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
    # The flag as 202610211900 seeds it: neither direction of the revision
    # resets a value an earlier test turned on.
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE global_feature_flags SET enabled = false WHERE name = 'flows_core'"
        )
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


def test_upgrade_leaves_the_flag_and_the_roles_alone(round_trip_db):
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

    assert not _flag_enabled(conn)
    assert _permissions(conn, owner) == ["assistants", "flows_view"]
    assert _permissions(conn, configurator) == ["assistants"]
    assert _permissions(conn, user) == ["assistants"]
    assert _permissions(conn, custom) == ["assistants"]


def test_downgrade_keeps_a_flag_an_administrator_turned_on(round_trip_db):
    conn, cfg = round_trip_db["conn"], round_trip_db["cfg"]
    owner = _insert_role(
        conn, predefined_source="Owner", permissions=["assistants", "flows_run"]
    )
    command.upgrade(cfg, REVISION)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE global_feature_flags SET enabled = true WHERE name = 'flows_core'"
        )

    command.downgrade(cfg, PRE_REVISION)

    assert _flag_enabled(conn)
    assert _permissions(conn, owner) == ["assistants", "flows_run"]
