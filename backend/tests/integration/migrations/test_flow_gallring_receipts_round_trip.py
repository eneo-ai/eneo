"""Round-trip the gallring job run and receipt tables (202610041200).

After the revision every index the ORM declares on the three gallring tables
exists with the declared columns, uniqueness and partial predicate; the
downgrade removes exactly those, and upgrading again restores them. The revision
is one transaction: a failed upgrade leaves nothing and re-runs.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.retention_tables import (
    RetentionJobRuns,
    RetentionReceiptItems,
    RetentionReceipts,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610041000"
REVISION = "202610041200"
_TABLES = (RetentionJobRuns, RetentionReceipts, RetentionReceiptItems)


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
    indexes = [index for table in _TABLES for index in table.__table__.indexes]
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


def _actual(engine: sa.Engine) -> dict[str, tuple[object, ...]]:
    inspector = sa.inspect(engine)
    tables = [table.__tablename__ for table in _TABLES]
    declared = _declared()
    return {
        index["name"]: _shape(
            [str(c) for c in (index.get("expressions") or index["column_names"])],
            bool(index["unique"]),
            "postgresql_where" in index["dialect_options"],
        )
        for table in tables
        if table in inspector.get_table_names()
        for index in inspector.get_indexes(table)
        if index["name"] in declared
    }


def _invalid_indexes(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
        return cursor.fetchone()[0]


def _tables(conn) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE tablename LIKE 'gallring_%%'"
        )
        return {row[0] for row in cursor.fetchall()}


def test_upgrade_creates_the_declared_tables_and_indexes(round_trip_db):
    conn, _, engine = round_trip_db

    assert _tables(conn) == {table.__tablename__ for table in _TABLES}
    assert _actual(engine) == _declared()
    assert _invalid_indexes(conn) == 0


def test_downgrade_removes_them_and_upgrade_restores_them(round_trip_db):
    conn, cfg, engine = round_trip_db

    command.downgrade(cfg, PRE_REVISION)
    assert _tables(conn) == set()
    assert _actual(engine) == {}

    command.upgrade(cfg, REVISION)
    assert _actual(engine) == _declared()


def test_only_one_running_execution_per_task(round_trip_db):
    conn, _, _ = round_trip_db
    insert = (
        "INSERT INTO gallring_job_runs (task, outcome, started_at, heartbeat_at) "
        "VALUES ('flows.housekeeping', 'running', now(), now())"
    )
    with conn.cursor() as cursor:
        cursor.execute(insert)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(insert)
        cursor.execute("DELETE FROM gallring_job_runs")


def test_orm_tables_match_the_reflected_columns(round_trip_db):
    _, _, engine = round_trip_db
    inspector = sa.inspect(engine)
    for table in _TABLES:
        reflected = {
            column["name"]: column["nullable"]
            for column in inspector.get_columns(table.__tablename__)
        }
        declared = {column.name: column.nullable for column in table.__table__.columns}
        assert reflected == declared, table.__tablename__


def test_a_failed_upgrade_leaves_nothing_and_re_runs(round_trip_db):
    conn, cfg, _ = round_trip_db
    command.downgrade(cfg, PRE_REVISION)
    with conn.cursor() as cursor:
        # A clashing relation makes the last CREATE TABLE of the revision fail.
        cursor.execute("CREATE TABLE gallring_receipt_items (id integer)")
    with pytest.raises(sa.exc.ProgrammingError):
        command.upgrade(cfg, REVISION)

    assert _tables(conn) == {"gallring_receipt_items"}  # only the clash
    with conn.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone()[0] == PRE_REVISION
        cursor.execute("DROP TABLE gallring_receipt_items")

    command.upgrade(cfg, REVISION)
    assert _tables(conn) == {table.__tablename__ for table in _TABLES}
