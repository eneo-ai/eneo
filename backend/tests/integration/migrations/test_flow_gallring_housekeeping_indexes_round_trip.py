"""Round-trip the flows housekeeping keyset indexes (202610041300).

The indexes are built CONCURRENTLY. A build that fails behind an old snapshot
leaves an INVALID index and no version stamp; the next upgrade replaces the
leftover and succeeds.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowRunAuditOutbox,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610041200"
REVISION = "202610041300"
_INDEXES = {
    "ix_flow_live_transcripts_unbound_created": FlowLiveTranscripts,
    "ix_flow_run_audit_outbox_delivered": FlowRunAuditOutbox,
}


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _connect(settings):
    conn = psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    conn.autocommit = True
    return conn


@pytest.fixture
def migration_db(test_settings):
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    command.upgrade(cfg, REVISION)
    conn = _connect(test_settings)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield conn, cfg, engine
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
        conn.close()


def _state(conn) -> dict[str, bool]:
    """Index name -> valid, for the revision's indexes that exist."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, x.indisvalid FROM pg_index x "
            "JOIN pg_class c ON c.oid = x.indexrelid WHERE c.relname = ANY(%s)",
            (sorted(_INDEXES),),
        )
        return dict(cursor.fetchall())


def _version(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        return cursor.fetchone()[0]


def _shape(engine, name: str) -> tuple[object, ...]:
    table = _INDEXES[name].__table__
    [reflected] = [
        index
        for index in sa.inspect(engine).get_indexes(table.name)
        if index["name"] == name
    ]
    [declared] = [index for index in table.indexes if index.name == name]
    return (
        tuple(reflected["column_names"]),
        "postgresql_where" in reflected["dialect_options"],
        tuple(column.name for column in declared.columns),
        declared.dialect_options["postgresql"]["where"] is not None,
    )


def test_upgrade_builds_the_declared_indexes_and_downgrade_removes_them(
    migration_db,
):
    conn, cfg, engine = migration_db

    assert _state(conn) == dict.fromkeys(_INDEXES, True)
    for name in _INDEXES:
        reflected_columns, reflected_partial, columns, partial = _shape(engine, name)
        assert (reflected_columns, reflected_partial) == (columns, partial)

    command.downgrade(cfg, PRE_REVISION)
    assert _state(conn) == {}
    command.upgrade(cfg, REVISION)
    assert _state(conn) == dict.fromkeys(_INDEXES, True)


def test_a_build_failed_behind_an_old_snapshot_is_replaced_on_rerun(
    migration_db, test_settings
):
    conn, cfg, _ = migration_db
    command.downgrade(cfg, PRE_REVISION)
    # An old snapshot (a long report, an idle transaction) makes the concurrent
    # build wait; the revision's 5 s lock timeout then aborts it.
    holder = _connect(test_settings)
    holder.autocommit = False
    try:
        with holder.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SELECT count(*) FROM flow_live_transcripts")
        with pytest.raises(sa.exc.OperationalError):
            command.upgrade(cfg, REVISION)
    finally:
        holder.rollback()
        holder.close()

    assert _version(conn) == PRE_REVISION
    assert False in _state(conn).values()  # an INVALID leftover

    command.upgrade(cfg, REVISION)

    assert _version(conn) == REVISION
    assert _state(conn) == dict.fromkeys(_INDEXES, True)
