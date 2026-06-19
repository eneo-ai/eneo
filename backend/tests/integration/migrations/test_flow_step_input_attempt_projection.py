"""Migration tests for Flow step input file attempt projection.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_step_input_attempt_projection.py -q
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260605_webhook_attempt_fk"
MIGRATION_REVISION = "20260607_step_input_attempt"
POSITIVE_CONSTRAINT = "ck_flow_run_step_input_files_attempt_no_positive"
REMOVED_INITIAL_CONSTRAINT = "ck_flow_run_step_input_files_attempt_no_initial"


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


def _constraint_definition(conn, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flow_run_step_input_files'
              AND constraint_row.conname = %s
            """,
            (constraint_name,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def test_upgrade_adds_positive_attempt_check_and_downgrade_removes_it(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    assert _constraint_definition(conn, POSITIVE_CONSTRAINT) is None
    assert _constraint_definition(conn, REMOVED_INITIAL_CONSTRAINT) is None

    command.upgrade(cfg, MIGRATION_REVISION)

    positive_definition = _constraint_definition(conn, POSITIVE_CONSTRAINT)
    assert positive_definition is not None
    assert "attempt_no >= 1" in positive_definition
    assert _constraint_definition(conn, REMOVED_INITIAL_CONSTRAINT) is None

    command.downgrade(cfg, PRIOR_REVISION)

    assert _constraint_definition(conn, POSITIVE_CONSTRAINT) is None
    assert _constraint_definition(conn, REMOVED_INITIAL_CONSTRAINT) is None
