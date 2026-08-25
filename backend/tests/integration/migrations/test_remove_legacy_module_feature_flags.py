"""Behavior coverage for retiring modules-as-feature-flags state."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202608211300"
CLEANUP_REVISION = "202608251000"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the isolated migration schema stable for the downgrade/upgrade."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """This test owns all data needed for its migration boundary."""
    yield


@pytest.fixture
def migration_db(test_settings):
    config = _alembic_cfg(test_settings.sync_database_url)
    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    connection.autocommit = True
    command.upgrade(config, CLEANUP_REVISION)
    try:
        yield connection, config
    finally:
        connection.close()


def _insert_tenant(connection) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), %s, 1000000, 'active')
            RETURNING id
            """,
            (f"module-cleanup-{uuid4().hex[:8]}",),
        )
        return cursor.fetchone()[0]


def _insert_module(connection, name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO modules (id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, now(), now())
            RETURNING id
            """,
            (name,),
        )
        return cursor.fetchone()[0]


def _assign_module(
    connection,
    *,
    tenant_id: str,
    module_id: str,
    redirect_uris: list[str] | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants_modules (tenant_id, module_id, redirect_uris)
            VALUES (%s, %s, %s)
            """,
            (
                tenant_id,
                module_id,
                Json(redirect_uris) if redirect_uris is not None else None,
            ),
        )


def _module_names(connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM modules")
        return {row[0] for row in cursor.fetchall()}


def _assigned_module_names(connection, tenant_id: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT module.name
            FROM modules AS module
            JOIN tenants_modules AS assignment ON assignment.module_id = module.id
            WHERE assignment.tenant_id = %s
            """,
            (tenant_id,),
        )
        return {row[0] for row in cursor.fetchall()}


def test_upgrade_removes_only_legacy_assignments_and_preserves_installations(
    migration_db,
) -> None:
    connection, config = migration_db
    command.downgrade(config, PRE_REVISION)

    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM modules WHERE name IN ('eneo-applications', 'SWE Models')"
        )

    tenant_id = _insert_tenant(connection)
    configured_tenant_id = _insert_tenant(connection)
    legacy_application_id = _insert_module(connection, "eneo-applications")
    legacy_swe_id = _insert_module(connection, "SWE Models")
    legacy_custom_name = f"legacy-{uuid4().hex[:8]}"
    installed_name = f"installed-{uuid4().hex[:8]}"
    unbound_name = f"unbound-{uuid4().hex[:8]}"
    legacy_custom_id = _insert_module(connection, legacy_custom_name)
    installed_id = _insert_module(connection, installed_name)
    unbound_id = _insert_module(connection, unbound_name)

    _assign_module(
        connection,
        tenant_id=tenant_id,
        module_id=legacy_application_id,
    )
    _assign_module(
        connection,
        tenant_id=configured_tenant_id,
        module_id=legacy_application_id,
        redirect_uris=["https://applications.example.com/callback"],
    )
    _assign_module(
        connection,
        tenant_id=tenant_id,
        module_id=legacy_swe_id,
        redirect_uris=["https://legacy.example.com/callback"],
    )
    _assign_module(connection, tenant_id=tenant_id, module_id=legacy_custom_id)
    _assign_module(
        connection,
        tenant_id=tenant_id,
        module_id=installed_id,
        redirect_uris=["https://module.example.com/callback"],
    )
    _assign_module(
        connection,
        tenant_id=tenant_id,
        module_id=unbound_id,
        redirect_uris=["https://unbound.example.com/callback"],
    )

    command.upgrade(config, CLEANUP_REVISION)

    assert _assigned_module_names(connection, tenant_id) == {
        installed_name,
        unbound_name,
    }
    assert _assigned_module_names(connection, configured_tenant_id) == {
        "eneo-applications"
    }
    assert "eneo-applications" in _module_names(connection)
    assert "SWE Models" not in _module_names(connection)
    assert legacy_custom_name in _module_names(connection)
