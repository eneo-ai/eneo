"""PostgreSQL migration contract for bounded Flow attempt admission indexes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607271700_call_input_indexes"
MIGRATION_REVISION = "202607291800_attempt_admit_idx"
INDEXES = {
    "ix_flow_step_attempts_run_step_order_attempt": (
        "flow_step_attempts",
        ("flow_run_id", "step_order", "attempt_no"),
    ),
    "ix_flow_step_results_run_step_order": (
        "flow_step_results",
        ("flow_run_id", "step_order"),
    ),
}


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    yield


@pytest.fixture
def fresh_chain_db(
    test_settings,
) -> Iterator[tuple[PsycopgConnection, Config]]:
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(test_settings.sync_database_url)
    conn.autocommit = True

    reset_public_schema(conn)
    command.upgrade(cfg, PRIOR_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _index_metadata(
    conn: PsycopgConnection,
    *,
    table_name: str,
    index_name: str,
) -> tuple[bool, bool, bool, bool, str, tuple[str, ...], tuple[int, ...]] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indisunique,
                index_metadata.indpred IS NULL,
                access_method.amname,
                array_agg(
                    pg_get_indexdef(
                        index_metadata.indexrelid,
                        key_position.position,
                        true
                    )
                    ORDER BY key_position.position
                ),
                index_metadata.indoption::smallint[]
            FROM pg_class AS index_row
            JOIN pg_namespace AS namespace_row
              ON namespace_row.oid = index_row.relnamespace
            JOIN pg_index AS index_metadata
              ON index_metadata.indexrelid = index_row.oid
            JOIN pg_class AS table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN pg_namespace AS table_namespace_row
              ON table_namespace_row.oid = table_row.relnamespace
            JOIN pg_am AS access_method
              ON access_method.oid = index_row.relam
            JOIN LATERAL generate_series(
                1,
                index_metadata.indnkeyatts
            ) AS key_position(position)
              ON true
            WHERE namespace_row.nspname = 'public'
              AND table_namespace_row.nspname = 'public'
              AND table_row.relname = %s
              AND index_row.relname = %s
            GROUP BY
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indisunique,
                index_metadata.indpred,
                index_metadata.indoption,
                access_method.amname
            """,
            (table_name, index_name),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return (
        row[0],
        row[1],
        row[2],
        row[3],
        row[4],
        tuple(row[5]),
        tuple(row[6]),
    )


def _assert_indexes_present(conn: PsycopgConnection) -> None:
    for index_name, (table_name, columns) in INDEXES.items():
        assert _index_metadata(
            conn,
            table_name=table_name,
            index_name=index_name,
        ) == (True, True, False, True, "btree", columns, (0,) * len(columns))


def _assert_indexes_absent(conn: PsycopgConnection) -> None:
    for index_name, (table_name, _) in INDEXES.items():
        assert (
            _index_metadata(
                conn,
                table_name=table_name,
                index_name=index_name,
            )
            is None
        )


def test_upgrade_downgrade_and_reupgrade_restore_attempt_admission_indexes(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    assert ScriptDirectory.from_config(cfg).get_heads() == [MIGRATION_REVISION]
    assert current_revisions(conn) == {PRIOR_REVISION}
    _assert_indexes_absent(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_indexes_present(conn)

    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    _assert_indexes_absent(conn)

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_indexes_present(conn)


def test_upgrade_resumes_after_first_index_was_committed(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX CONCURRENTLY ix_flow_step_attempts_run_step_order_attempt
            ON flow_step_attempts (flow_run_id, step_order, attempt_no)
            """
        )

    assert current_revisions(conn) == {PRIOR_REVISION}
    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_indexes_present(conn)


def test_upgrade_rejects_a_mismatched_named_index(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX CONCURRENTLY ix_flow_step_attempts_run_step_order_attempt
            ON flow_step_attempts (flow_run_id, attempt_no)
            """
        )

    with pytest.raises(RuntimeError, match="unexpected state"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _index_metadata(
        conn,
        table_name="flow_step_attempts",
        index_name="ix_flow_step_attempts_run_step_order_attempt",
    ) == (
        True,
        True,
        False,
        True,
        "btree",
        ("flow_run_id", "attempt_no"),
        (0, 0),
    )
    assert (
        _index_metadata(
            conn,
            table_name="flow_step_results",
            index_name="ix_flow_step_results_run_step_order",
        )
        is None
    )


def test_upgrade_rejects_a_mixed_direction_attempt_index(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX CONCURRENTLY ix_flow_step_attempts_run_step_order_attempt
            ON flow_step_attempts (flow_run_id, step_order DESC, attempt_no ASC)
            """
        )

    assert _index_metadata(
        conn,
        table_name="flow_step_attempts",
        index_name="ix_flow_step_attempts_run_step_order_attempt",
    ) == (
        True,
        True,
        False,
        True,
        "btree",
        ("flow_run_id", "step_order", "attempt_no"),
        (0, 3, 0),
    )
    with pytest.raises(RuntimeError, match="unexpected state"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert current_revisions(conn) == {PRIOR_REVISION}
    assert (
        _index_metadata(
            conn,
            table_name="flow_step_results",
            index_name="ix_flow_step_results_run_step_order",
        )
        is None
    )
