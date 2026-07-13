"""Migration contract for the tenant-admin Flow retention control plane.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_retention_admin_policy.py -q
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607111200_file_tenant_fks"
MIGRATION_REVISION = "202607131200_flow_retention"
COLUMNS = (
    "flow_run_history_retention_days",
    "flow_runtime_upload_abandonment_days",
)
CONSTRAINTS = (
    "ck_tenants_flow_run_history_retention_days_range",
    "ck_tenants_flow_runtime_upload_abandonment_days_range",
)


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
    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        command.upgrade(cfg, "head")
        conn.close()


def _column_contract(conn) -> dict[str, tuple[str, str]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'tenants'
              AND column_name = ANY(%s)
            ORDER BY column_name
            """,
            (list(COLUMNS),),
        )
        return {name: (nullable, default) for name, nullable, default in cursor}


def _constraint_contract(conn) -> dict[str, tuple[bool, str]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT constraint_row.conname,
                   constraint_row.convalidated,
                   pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row
              ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'tenants'
              AND constraint_row.conname = ANY(%s)
            ORDER BY constraint_row.conname
            """,
            (list(CONSTRAINTS),),
        )
        return {name: (validated, definition) for name, validated, definition in cursor}


def _set_policy_value(conn, column_name: str, value: int | None) -> None:
    assert column_name in COLUMNS
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE tenants
            SET {column_name} = %s
            WHERE id = (SELECT id FROM tenants ORDER BY id LIMIT 1)
            """,
            (value,),
        )


def _insert_policy_test_tenant(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (
                gen_random_uuid(),
                'flow-retention-migration-contract',
                1000000,
                'active'
            )
            """
        )


def test_flow_retention_columns_round_trip_with_database_range_guards(
    migration_db,
) -> None:
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    assert _column_contract(conn) == {}

    command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert _column_contract(conn) == {
        column_name: ("YES", None) for column_name in COLUMNS
    }
    constraint_contract = _constraint_contract(conn)
    assert set(constraint_contract) == set(CONSTRAINTS)
    for validated, definition in constraint_contract.values():
        assert validated is True
        assert ">= 1" in definition
        assert "<= 2555" in definition

    _insert_policy_test_tenant(conn)
    for column_name in COLUMNS:
        for allowed_value in (None, 1, 2555):
            _set_policy_value(conn, column_name, allowed_value)
        for rejected_value in (0, 2556):
            with pytest.raises(psycopg2.errors.CheckViolation):
                _set_policy_value(conn, column_name, rejected_value)

    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _column_contract(conn) == {}

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert set(_column_contract(conn)) == set(COLUMNS)
