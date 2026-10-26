"""Reuse the bookkeeping migration round-trip witness for the generic execution table."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa

from alembic import command
from alembic.config import Config
from eneo.data_retention.domain.retention import RetentionErrorCode
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import InfoBlobReferences, Questions
from eneo.database.tables.retention_tables import RetentionJobRuns
from eneo.database.tables.sessions_table import Sessions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610011100"
REVISION = "202610071400"
_TABLES = (RetentionJobRuns, Files, Questions, AppRuns, Sessions, InfoBlobReferences)
_ADOPTER_INDEXES = frozenset(
    {
        "ix_files_root_created_id",
        "ix_files_parent_file_id_id",
        "ix_questions_retention_owner_created_id",
        "ix_app_runs_retention_owner_created_id",
        "ix_sessions_created_id",
        "ix_info_blob_references_question_id",
    }
)
_OLD_INDEXES = {
    "ix_files_parent_file_id": ["parent_file_id"],
    "ix_questions_assistant_created": ["assistant_id", "created_at"],
    "idx_questions_assistant_created": ["assistant_id", "created_at"],
    "ix_app_runs_app_created": ["app_id", "created_at"],
    "created_at_idx": ["created_at"],
    "idx_sessions_created_at": ["created_at"],
}


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def round_trip_db(test_settings):
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield conn, cfg, engine
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
        conn.close()


def _shape(columns: list[str], unique: bool, partial: bool) -> tuple[object, ...]:
    # Reflection reports the sort direction in dialect options, not in the column.
    normalized = [
        column.lower().replace(" ", "").removesuffix("desc") for column in columns
    ]
    return (tuple(normalized), unique, partial)


def _declared() -> dict[str, tuple[object, ...]]:
    indexes = [
        index
        for table in _TABLES
        for index in table.__table__.indexes
        if table is RetentionJobRuns or index.name in _ADOPTER_INDEXES
    ]
    return {
        str(index.name): _shape(
            [
                expression.name
                if isinstance(expression, sa.Column)
                else str(expression)
                for expression in index.expressions
            ],
            bool(index.unique),
            index.dialect_options["postgresql"]["where"] is not None,
        )
        for index in indexes
    }


def _actual(
    engine: sa.Engine, names: frozenset[str] | None = None
) -> dict[str, tuple[object, ...]]:
    inspector = sa.inspect(engine)
    tables = [table.__tablename__ for table in _TABLES]
    selected = names if names is not None else frozenset(_declared())
    return {
        index["name"]: _shape(
            [str(c) for c in (index.get("expressions") or index["column_names"])],
            bool(index["unique"]),
            "postgresql_where" in index["dialect_options"],
        )
        for table in tables
        if table in inspector.get_table_names()
        for index in inspector.get_indexes(table)
        if index["name"] in selected
    }


def _invalid_indexes(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
        return cursor.fetchone()[0]


def _tables(conn) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE tablename = 'retention_job_runs'"
        )
        return {row[0] for row in cursor.fetchall()}


def test_downgrade_removes_them_and_upgrade_restores_them(round_trip_db):
    """Kills an incomplete upgrade, a mismatched index, a downgrade leaving the
    table, or an error code the migrated CHECK refuses."""
    conn, cfg, engine = round_trip_db
    assert _tables(conn) == {"retention_job_runs"}
    assert _actual(engine) == _declared()
    assert _actual(engine, frozenset(_OLD_INDEXES)) == {}
    assert _invalid_indexes(conn) == 0
    columns = sa.inspect(engine).get_columns("retention_job_runs")
    assert {c["name"]: c["nullable"] for c in columns} == {
        c.name: c.nullable for c in RetentionJobRuns.__table__.columns
    }
    [error_codes] = [
        check["sqltext"]
        for check in sa.inspect(engine).get_check_constraints("retention_job_runs")
        if check["name"] == "ck_retention_job_runs_error_code"
    ]
    assert all(f"'{code.value}'" in error_codes for code in RetentionErrorCode)

    command.downgrade(cfg, PRE_REVISION)
    assert _tables(conn) == set()
    assert _actual(engine) == {}
    assert _actual(engine, frozenset(_OLD_INDEXES)) == {
        name: _shape(columns, False, False) for name, columns in _OLD_INDEXES.items()
    }

    command.upgrade(cfg, REVISION)
    assert _actual(engine) == _declared()
    assert _actual(engine, frozenset(_OLD_INDEXES)) == {}


def test_upgrade_emits_bookkeeping_ddl_offline():
    """Kills catalog access during offline migration generation."""
    backend_dir = Path(__file__).parent.parent.parent.parent
    output = StringIO()
    cfg = Config(str(backend_dir / "alembic.ini"), output_buffer=output)
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option(
        "sqlalchemy.url", "postgresql://offline:offline@localhost/offline"
    )
    command.upgrade(cfg, f"{PRE_REVISION}:{REVISION}", sql=True)
    ddl = output.getvalue()
    assert "CREATE TABLE retention_job_runs" in ddl
    assert "CREATE UNIQUE INDEX uq_retention_job_runs_running_task" in ddl
    assert "ix_retention_job_runs_task_overdue_observed_at" in ddl
    for name in _ADOPTER_INDEXES:
        assert f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name}" in ddl
    assert "ON files (created_at, id) WHERE parent_file_id IS NULL" in ddl
    for name in _OLD_INDEXES:
        assert f"DROP INDEX CONCURRENTLY IF EXISTS {name}" in ddl
    # Concurrent work precedes the versioned table transaction so a failed
    # index build cannot leave an unversioned table that prevents retry.
    assert ddl.index("CREATE TABLE retention_job_runs") > max(
        ddl.index(f"DROP INDEX CONCURRENTLY IF EXISTS {name}") for name in _OLD_INDEXES
    )
