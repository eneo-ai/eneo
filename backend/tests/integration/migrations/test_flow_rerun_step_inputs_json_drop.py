"""Migration tests for deleting duplicate Flow rerun step-input JSONB.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_rerun_step_inputs_json_drop.py -q
"""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260611_flow_class_retention"
MIGRATION_REVISION = "20260611_drop_rerun_step_inputs"
TABLE_NAME = "flow_run_rerun_operations"
COLUMN_NAME = "step_inputs_json"


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


def _column_metadata(conn) -> dict[str, str] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, udt_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = %s
            """,
            (TABLE_NAME, COLUMN_NAME),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"data_type": row[0], "udt_name": row[1], "is_nullable": row[2]}


def test_upgrade_drops_step_inputs_json_and_downgrade_restores_nullable_jsonb(
    migration_db,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    assert _column_metadata(conn) == {
        "data_type": "jsonb",
        "udt_name": "jsonb",
        "is_nullable": "YES",
    }

    command.upgrade(cfg, MIGRATION_REVISION)
    assert _column_metadata(conn) is None

    command.downgrade(cfg, PRIOR_REVISION)
    assert _column_metadata(conn) == {
        "data_type": "jsonb",
        "udt_name": "jsonb",
        "is_nullable": "YES",
    }
