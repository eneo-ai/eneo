"""Migration tests for Flow result file attempt ownership.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_result_file_attempt_fk.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260605_builder_session_idx"
MIGRATION_REVISION = "20260605_flow_result_file_fk"
CONSTRAINT_NAME = "fk_flow_run_step_result_files_step_attempt"
SENTINEL_FILE_ID = "00000000-0000-4000-8000-000000000234"
RESULT_FILE_SOURCE = "generated_output"


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
    _clear_seeded_rows(conn)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _clear_seeded_rows(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                "DELETE FROM flow_run_step_result_files WHERE file_id = %s",
                (SENTINEL_FILE_ID,),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    return row[0] if row else None


def _constraint_definition(conn, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flow_run_step_result_files'
              AND constraint_row.conname = %s
            """,
            (constraint_name,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _insert_orphan_result_file(
    conn,
    *,
    result_file_id: str,
    flow_run_id: str,
    step_id: str,
    attempt_no: int,
) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                """
                INSERT INTO flow_run_step_result_files (
                    id,
                    tenant_id,
                    flow_id,
                    flow_run_id,
                    step_result_id,
                    step_id,
                    step_order,
                    attempt_no,
                    file_id,
                    ordinal,
                    source
                )
                VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, 0, %s)
                """,
                (
                    result_file_id,
                    str(uuid4()),
                    str(uuid4()),
                    flow_run_id,
                    str(uuid4()),
                    step_id,
                    attempt_no,
                    SENTINEL_FILE_ID,
                    RESULT_FILE_SOURCE,
                ),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def test_upgrade_aborts_when_result_file_has_no_attempt(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    result_file_id = str(uuid4())
    flow_run_id = str(uuid4())
    step_id = str(uuid4())
    _insert_orphan_result_file(
        conn,
        result_file_id=result_file_id,
        flow_run_id=flow_run_id,
        step_id=step_id,
        attempt_no=7,
    )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert CONSTRAINT_NAME in message
    assert "1 flow_run_step_result_files rows" in message
    assert f"id={result_file_id}" in message
    assert f"flow_run_id={flow_run_id}" in message
    assert f"step_id={step_id}" in message
    assert "tenant_id=" in message
    assert "flow_id=" in message
    assert "step_order=1" in message
    assert "attempt_no=7" in message
    assert "step_result_id=" in message
    assert f"file_id={SENTINEL_FILE_ID}" in message
    assert "ordinal=0" in message
    assert f"source={RESULT_FILE_SOURCE}" in message
    assert "created_at=" in message
    assert "Delete or repair orphan result files" in message
    assert _current_revision(conn) == PRIOR_REVISION
    assert _constraint_definition(conn, CONSTRAINT_NAME) is None


def test_upgrade_adds_cascade_fk_and_downgrade_drops_it(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    command.upgrade(cfg, MIGRATION_REVISION)

    definition = _constraint_definition(conn, CONSTRAINT_NAME)
    assert definition is not None
    assert "FOREIGN KEY (flow_run_id, step_id, attempt_no)" in definition
    assert (
        "REFERENCES flow_step_attempts(flow_run_id, step_id, attempt_no)" in definition
    )
    assert "ON DELETE CASCADE" in definition

    command.downgrade(cfg, PRIOR_REVISION)

    assert _constraint_definition(conn, CONSTRAINT_NAME) is None
