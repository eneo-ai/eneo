from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy.exc import DBAPIError

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import reset_public_schema

pytestmark = pytest.mark.migration_isolation

PREVIOUS_REVISION = "202608281300"
POLICY_REVISION = "202608301525"
VALIDATED_REVISION = "202608301535"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
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
    reset_public_schema(conn)
    command.upgrade(cfg, PREVIOUS_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _seed_existing_duration_values(conn) -> dict[str, object]:
    tenant_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id, name, display_name, quota_limit, provisioning,
                security_enabled, state, flow_run_history_retention_days
            ) VALUES (%s, %s, %s, 100000, false, false, 'active', 30)
            """,
            (tenant_id, f"retention-{tenant_id}", f"Retention {tenant_id}"),
        )
        cur.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, data_retention_days)
            VALUES (%s, %s, %s, 60)
            """,
            (space_id, f"Retention Space {space_id}", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id, name, tenant_id, space_id, data_retention_days
            ) VALUES (%s, %s, %s, %s, 90)
            """,
            (flow_id, f"Retention Flow {flow_id}", tenant_id, space_id),
        )
    return {"tenant_id": tenant_id, "space_id": space_id, "flow_id": flow_id}


def test_existing_values_become_preserve_and_constraints_validate(
    migration_db,
) -> None:
    conn, cfg = migration_db
    seeded = _seed_existing_duration_values(conn)

    command.upgrade(cfg, POLICY_REVISION)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT flow_run_history_retention_mode,
                   flow_run_history_retention_days
            FROM tenants WHERE id = %s
            """,
            (seeded["tenant_id"],),
        )
        assert cur.fetchone() == ("preserve", 30)
        cur.execute(
            """
            SELECT data_retention_days,
                   flow_run_history_retention_mode,
                   flow_run_history_retention_days
            FROM spaces WHERE id = %s
            """,
            (seeded["space_id"],),
        )
        assert cur.fetchone() == (60, "preserve", 60)
        cur.execute(
            """
            SELECT flow_run_history_retention_mode,
                   flow_run_history_retention_days
            FROM flows WHERE id = %s
            """,
            (seeded["flow_id"],),
        )
        assert cur.fetchone() == ("preserve", 90)
        cur.execute(
            """
            SELECT convalidated FROM pg_constraint
            WHERE conname = 'ck_spaces_flow_run_history_retention_complete'
            """
        )
        assert cur.fetchone() == (False,)
        cur.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE indexname = 'ix_flow_runs_tenant_terminal_retention_anchor'
            """
        )
        tenant_index = cur.fetchone()
        assert tenant_index is not None
        assert "(tenant_id, COALESCE(finished_at, created_at), id)" in tenant_index[0]

    command.upgrade(cfg, VALIDATED_REVISION)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT convalidated FROM pg_constraint
            WHERE conname = 'ck_spaces_flow_run_history_retention_complete'
            """
        )
        assert cur.fetchone() == (True,)

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants SET flow_run_history_retention_mode = NULL
                WHERE id = %s
                """,
                (seeded["tenant_id"],),
            )

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE flows SET flow_run_history_retention_mode = 'automatic'
                WHERE id = %s
                """,
                (seeded["flow_id"],),
            )

    command.downgrade(cfg, PREVIOUS_REVISION)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_retention_days FROM flows WHERE id = %s
            """,
            (seeded["flow_id"],),
        )
        assert cur.fetchone() == (90,)
        cur.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE indexname = 'ix_flow_runs_terminal_retention_anchor'
            """
        )
        assert cur.fetchone() is not None


def test_downgrade_refuses_to_erase_review_policy_semantics(migration_db) -> None:
    conn, cfg = migration_db
    seeded = _seed_existing_duration_values(conn)
    command.upgrade(cfg, VALIDATED_REVISION)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE flows SET flow_run_history_retention_mode = 'review_required'
            WHERE id = %s
            """,
            (seeded["flow_id"],),
        )

    with pytest.raises(DBAPIError, match="review_required"):
        command.downgrade(cfg, PREVIOUS_REVISION)
