"""PostgreSQL 13 migration contract for Flow retention barriers."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy.exc import InternalError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607131200_flow_retention"
MIGRATION_REVISION = "202607151200_flow_retention_barriers"
TENANT_CONSTRAINT = "ck_tenants_flow_run_history_minimum_retention_days_range"
CLASSIFICATION_CONSTRAINTS = (
    "ck_flow_classification_retention_policy_days_range",
    "ck_flow_classification_retention_policy_minimum_days_range",
    "ck_flow_classification_retention_policy_has_value",
)


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg13",
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    )
    with postgres:
        postgres.get_connection_url()
        yield postgres


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


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


def _columns(conn, table_name: str, column_names: tuple[str, ...]):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = ANY(%s)
            ORDER BY column_name
            """,
            (table_name, list(column_names)),
        )
        return {name: (nullable, default) for name, nullable, default in cursor}


def _constraints(conn, table_name: str, constraint_names: tuple[str, ...]):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT constraint_row.conname,
                   constraint_row.convalidated,
                   pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = ANY(%s)
            ORDER BY constraint_row.conname
            """,
            (table_name, list(constraint_names)),
        )
        return {name: (validated, definition) for name, validated, definition in cursor}


def test_upgrade_adds_inactive_checked_barriers_on_postgresql_13(migration_db) -> None:
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    with conn.cursor() as cursor:
        cursor.execute("SHOW server_version_num")
        assert cursor.fetchone()[0].startswith("13")

    tenant_columns = (
        "flow_run_history_minimum_retention_days",
        "flow_run_history_no_purge",
    )
    classification_columns = (
        "minimum_retention_days",
        "no_purge",
    )
    assert _columns(conn, "tenants", tenant_columns) == {}
    assert (
        _columns(
            conn,
            "flow_classification_retention_policies",
            classification_columns,
        )
        == {}
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert _columns(conn, "tenants", tenant_columns) == {
        "flow_run_history_minimum_retention_days": ("YES", None),
        "flow_run_history_no_purge": ("NO", "false"),
    }
    assert _columns(
        conn,
        "flow_classification_retention_policies",
        classification_columns,
    ) == {
        "minimum_retention_days": ("YES", None),
        "no_purge": ("NO", "false"),
    }


def test_barrier_constraints_accept_boundaries_and_reject_empty_rows(
    migration_db,
) -> None:
    conn = migration_db["conn"]
    command.upgrade(migration_db["cfg"], MIGRATION_REVISION)

    tenant_constraints = _constraints(conn, "tenants", (TENANT_CONSTRAINT,))
    classification_constraints = _constraints(
        conn,
        "flow_classification_retention_policies",
        CLASSIFICATION_CONSTRAINTS,
    )
    assert set(tenant_constraints) == {TENANT_CONSTRAINT}
    assert set(classification_constraints) == set(CLASSIFICATION_CONSTRAINTS)
    assert all(validated for validated, _definition in tenant_constraints.values())
    assert all(
        validated for validated, _definition in classification_constraints.values()
    )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (gen_random_uuid(), 'flow-retention-barriers', 1000000, 'active')
            RETURNING id, flow_run_history_no_purge
            """
        )
        tenant_id, tenant_no_purge = cursor.fetchone()
        assert tenant_no_purge is False
        cursor.execute(
            """
            INSERT INTO security_classifications (
                id, name, description, security_level, tenant_id
            )
            VALUES (gen_random_uuid(), 'Barrier class', NULL, 3, %s)
            RETURNING id
            """,
            (tenant_id,),
        )
        classification_id = cursor.fetchone()[0]

    for allowed_minimum in (None, 1, 2555):
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tenants
                SET flow_run_history_minimum_retention_days = %s
                WHERE id = %s
                """,
                (allowed_minimum, tenant_id),
            )
    for rejected_minimum in (0, 2556):
        with pytest.raises(psycopg2.errors.CheckViolation), conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tenants
                SET flow_run_history_minimum_retention_days = %s
                WHERE id = %s
                """,
                (rejected_minimum, tenant_id),
            )

    with pytest.raises(psycopg2.errors.CheckViolation), conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO flow_classification_retention_policies (
                tenant_id, security_classification_id, data_retention_days,
                minimum_retention_days, no_purge
            )
            VALUES (%s, %s, NULL, NULL, false)
            """,
            (tenant_id, classification_id),
        )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO flow_classification_retention_policies (
                tenant_id, security_classification_id, data_retention_days,
                minimum_retention_days
            )
            VALUES (%s, %s, NULL, 2555)
            RETURNING no_purge
            """,
            (tenant_id, classification_id),
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(
            """
            UPDATE flow_classification_retention_policies
            SET minimum_retention_days = NULL, no_purge = true
            WHERE tenant_id = %s AND security_classification_id = %s
            """,
            (tenant_id, classification_id),
        )

    with pytest.raises(psycopg2.errors.CheckViolation), conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE flow_classification_retention_policies
            SET no_purge = false
            WHERE tenant_id = %s AND security_classification_id = %s
            """,
            (tenant_id, classification_id),
        )

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def test_downgrade_rejects_barrier_only_policy_then_round_trips(migration_db) -> None:
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    command.upgrade(cfg, MIGRATION_REVISION)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (
                gen_random_uuid(),
                'flow-retention-barrier-downgrade',
                1000000,
                'active'
            )
            RETURNING id
            """
        )
        tenant_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO security_classifications (
                id, name, description, security_level, tenant_id
            )
            VALUES (gen_random_uuid(), 'Downgrade barrier', NULL, 3, %s)
            RETURNING id
            """,
            (tenant_id,),
        )
        classification_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO flow_classification_retention_policies (
                tenant_id, security_classification_id, data_retention_days,
                minimum_retention_days, no_purge
            )
            VALUES (%s, %s, NULL, 30, false)
            """,
            (tenant_id, classification_id),
        )

    with pytest.raises(
        InternalError,
        match="Cannot downgrade Flow retention barriers while barrier data exists",
    ):
        command.downgrade(cfg, PRIOR_REVISION)

    assert current_revisions(conn) == {MIGRATION_REVISION}
    assert _columns(
        conn,
        "flow_classification_retention_policies",
        ("minimum_retention_days", "no_purge"),
    )

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    assert (
        _columns(
            conn,
            "flow_classification_retention_policies",
            ("minimum_retention_days", "no_purge"),
        )
        == {}
    )

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
