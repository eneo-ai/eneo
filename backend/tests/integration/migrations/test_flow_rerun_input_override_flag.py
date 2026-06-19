"""Migration tests for Flow rerun root step-input override state.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_rerun_input_override_flag.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260608_result_file_no_default"
MIGRATION_REVISION = "20260608_rerun_input_flag"
TABLE_NAME = "flow_run_rerun_operations"
COLUMN_NAME = "root_step_input_override_requested"


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


def _column_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s
                  AND column_name = %s
            )
            """,
            (TABLE_NAME, COLUMN_NAME),
        )
        return bool(cur.fetchone()[0])


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


def _insert_rerun_operation(
    conn,
    *,
    request_fingerprint: str,
    step_inputs_json: dict[str, object] | None,
) -> str:
    operation_id = str(uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                """
                INSERT INTO flow_run_rerun_operations (
                    id,
                    tenant_id,
                    flow_id,
                    flow_run_id,
                    rerun_step_id,
                    rerun_step_order,
                    root_attempt_no,
                    status,
                    request_fingerprint,
                    expected_run_revision,
                    accepted_run_revision,
                    reason,
                    input_payload_json,
                    step_inputs_json,
                    requested_by_principal_type,
                    requested_by_user_id
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    1,
                    2,
                    'queued',
                    %s,
                    1,
                    1,
                    'rerun',
                    NULL,
                    %s,
                    'user',
                    %s
                )
                """,
                (
                    operation_id,
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    request_fingerprint,
                    Json(step_inputs_json) if step_inputs_json is not None else None,
                    str(uuid4()),
                ),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")
    return operation_id


def _override_flags(conn) -> dict[str, bool]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id::text, {COLUMN_NAME}
            FROM {TABLE_NAME}
            WHERE request_fingerprint IN ('inherited-inputs', 'explicit-empty-inputs')
            ORDER BY request_fingerprint
            """
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _insert_rerun_operation_without_override_flag(conn) -> None:
    _insert_rerun_operation(
        conn,
        request_fingerprint="missing-override-flag",
        step_inputs_json=None,
    )


def test_upgrade_backfills_override_flag_and_downgrade_drops_column(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    assert _column_exists(conn) is False
    inherited_id = _insert_rerun_operation(
        conn,
        request_fingerprint="inherited-inputs",
        step_inputs_json=None,
    )
    override_id = _insert_rerun_operation(
        conn,
        request_fingerprint="explicit-empty-inputs",
        step_inputs_json={"root-step": {"file_ids": []}},
    )

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _column_default(conn) is None
    assert _override_flags(conn) == {
        inherited_id: False,
        override_id: True,
    }
    with pytest.raises(psycopg2.errors.NotNullViolation):
        _insert_rerun_operation_without_override_flag(conn)

    command.downgrade(cfg, PRIOR_REVISION)

    assert _column_exists(conn) is False
