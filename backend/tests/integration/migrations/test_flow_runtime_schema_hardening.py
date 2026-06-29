"""Migration tests for Flow runtime schema hardening.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_runtime_schema_hardening.py -q
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202606281530_builder_state"
MIGRATION_REVISION = "202606291900_flow_runtime_schema"
SENTINEL_ATTEMPT_ID = "00000000-0000-4000-8000-000000000912"

CHECKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("flow_steps", "ck_flow_steps_step_order_positive", ("step_order >= 1",)),
    (
        "flow_step_results",
        "ck_flow_step_results_step_order_positive",
        ("step_order >= 1",),
    ),
    (
        "flow_step_results",
        "ck_flow_step_results_current_attempt_no_positive",
        ("current_attempt_no IS NULL", "current_attempt_no >= 1"),
    ),
    (
        "flow_step_attempts",
        "ck_flow_step_attempts_step_order_positive",
        ("step_order >= 1",),
    ),
    (
        "flow_step_attempts",
        "ck_flow_step_attempts_attempt_no_positive",
        ("attempt_no >= 1",),
    ),
)
INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_flow_steps_assistant_id", ("assistant_id",)),
    ("ix_flow_step_results_assistant_id", ("assistant_id",)),
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
    _delete_sentinel_attempt(conn)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _delete_sentinel_attempt(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _constraint_definition(conn, table_name: str, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _index_columns(conn, index_name: str) -> tuple[str, ...] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT array_agg(attribute_row.attname ORDER BY index_key.ordinality)
            FROM pg_class index_row
            JOIN pg_index index_metadata
              ON index_metadata.indexrelid = index_row.oid
            JOIN pg_class table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN unnest(index_metadata.indkey)
              WITH ORDINALITY AS index_key(attnum, ordinality)
              ON true
            JOIN pg_attribute attribute_row
              ON attribute_row.attrelid = table_row.oid
             AND attribute_row.attnum = index_key.attnum
            WHERE index_row.relname = %s
            """,
            (index_name,),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return tuple(row[0])


def _assert_schema_present(conn) -> None:
    for table_name, constraint_name, expected_fragments in CHECKS:
        definition = _constraint_definition(conn, table_name, constraint_name)
        assert definition is not None
        for expected in expected_fragments:
            assert expected in definition

    for index_name, expected_columns in INDEXES:
        assert _index_columns(conn, index_name) == expected_columns


def _assert_schema_absent(conn) -> None:
    for table_name, constraint_name, _ in CHECKS:
        assert _constraint_definition(conn, table_name, constraint_name) is None

    for index_name, _ in INDEXES:
        assert _index_columns(conn, index_name) is None


def _insert_invalid_attempt_no(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                """
                INSERT INTO flow_step_attempts (
                    id,
                    flow_run_id,
                    flow_id,
                    tenant_id,
                    step_id,
                    step_order,
                    attempt_no,
                    status,
                    started_at
                )
                VALUES (%s, %s, %s, %s, %s, 1, 0, 'started', now())
                """,
                (
                    SENTINEL_ATTEMPT_ID,
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                ),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def _delete_sentinel_attempt(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                "DELETE FROM flow_step_attempts WHERE id = %s",
                (SENTINEL_ATTEMPT_ID,),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def test_upgrade_adds_constraints_indexes_and_round_trips(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    _assert_schema_absent(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    _assert_schema_present(conn)

    command.downgrade(cfg, PRIOR_REVISION)
    _assert_schema_absent(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    _assert_schema_present(conn)


def test_upgrade_aborts_when_existing_attempt_has_non_positive_attempt_no(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    _insert_invalid_attempt_no(conn)

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert "ck_flow_step_attempts_attempt_no_positive" in message
    assert "1 flow_step_attempts.attempt_no rows are less than 1" in message
    assert f"id={SENTINEL_ATTEMPT_ID}" in message
    assert "attempt_no=0" in message
    assert "Repair or delete those rows" in message
    assert PRIOR_REVISION in current_revisions(conn)
