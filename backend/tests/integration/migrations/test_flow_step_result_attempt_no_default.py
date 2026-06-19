"""Migration tests for explicit Flow step-result file attempts.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_step_result_attempt_no_default.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260608_step_input_no_default"
MIGRATION_REVISION = "20260608_result_file_no_default"
TABLE_NAME = "flow_run_step_result_files"
COLUMN_NAME = "attempt_no"


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


def _column_default(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = %s
            """,
            (TABLE_NAME, COLUMN_NAME),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _insert_step_result_file_without_attempt(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_run_step_result_files (
                flow_run_id,
                flow_id,
                tenant_id,
                step_result_id,
                step_id,
                step_order,
                file_id,
                ordinal,
                source
            )
            VALUES (%s, %s, %s, %s, %s, 1, %s, 0, 'generated_output')
            """,
            (
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
            ),
        )


def test_upgrade_removes_attempt_default_and_downgrade_restores_it(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    assert _column_default(conn) == "1"

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _column_default(conn) is None
    with pytest.raises(psycopg2.errors.NotNullViolation):
        _insert_step_result_file_without_attempt(conn)

    command.downgrade(cfg, PRIOR_REVISION)

    assert _column_default(conn) == "1"
