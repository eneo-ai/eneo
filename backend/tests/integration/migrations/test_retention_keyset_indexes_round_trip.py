"""Round-trip the retention keyset indexes and retry failed concurrent builds.

The indexes are built CONCURRENTLY. A build that fails behind an old snapshot
leaves an INVALID index and no version stamp; the next upgrade replaces the
leftover and succeeds.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa
from psycopg2 import sql

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowRunAuditOutbox,
    FlowRuns,
)
from eneo.database.tables.questions_table import Questions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_REVISIONS = [
    pytest.param(
        (
            "202610051020",
            "202610061200",
            {
                "ix_questions_retention_owner_created_id": Questions,
                "ix_app_runs_retention_owner_created_id": AppRuns,
            },
        ),
        id="conversation-full-keyset",
    ),
    pytest.param(
        (
            "202610051010",
            "202610051020",
            {"ix_flow_runs_retention_receipt": FlowRuns},
        ),
        id="run-receipt-reference",
    ),
    pytest.param(
        (
            "202610041200",
            "202610041300",
            {
                "ix_flow_live_transcripts_unbound_created": FlowLiveTranscripts,
                "ix_flow_run_audit_outbox_delivered": FlowRunAuditOutbox,
            },
        ),
        id="flow-housekeeping",
    ),
    pytest.param(
        (
            "202610041300",
            "202610060100",
            {"ix_assistants_flow_managed_created_at_id": Assistants},
        ),
        id="managed-assistants",
    ),
]


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


@pytest.fixture(params=_REVISIONS)
def migration_db(test_settings, request):
    pre_revision, revision, indexes = request.param
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    command.upgrade(cfg, revision)
    conn = _connect(test_settings)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield conn, cfg, engine, pre_revision, revision, indexes
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
        conn.close()


def _state(conn, indexes) -> dict[str, bool]:
    """Index name -> valid, for the revision's indexes that exist."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, x.indisvalid FROM pg_index x "
            "JOIN pg_class c ON c.oid = x.indexrelid WHERE c.relname = ANY(%s)",
            (sorted(indexes),),
        )
        return dict(cursor.fetchall())


def _version(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        return cursor.fetchone()[0]


def _shape(engine, name: str, indexes) -> tuple[object, ...]:
    table = indexes[name].__table__
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
    conn, cfg, engine, pre_revision, revision, indexes = migration_db
    replaced = (
        {
            "ix_questions_assistant_created": (
                Questions,
                ("assistant_id", "created_at"),
            ),
            "idx_questions_assistant_created": (
                Questions,
                ("assistant_id", "created_at"),
            ),
            "ix_app_runs_app_created": (AppRuns, ("app_id", "created_at")),
        }
        if revision == "202610061200"
        else {}
    )

    assert _state(conn, indexes) == dict.fromkeys(indexes, True)
    assert _state(conn, replaced) == {}
    for name in indexes:
        reflected_columns, reflected_partial, columns, partial = _shape(
            engine, name, indexes
        )
        assert (reflected_columns, reflected_partial) == (columns, partial)

    command.downgrade(cfg, pre_revision)
    assert _state(conn, indexes) == {}
    assert _state(conn, replaced) == dict.fromkeys(replaced, True)
    for name, (model, columns) in replaced.items():
        [reflected] = [
            index
            for index in sa.inspect(engine).get_indexes(model.__table__.name)
            if index["name"] == name
        ]
        assert tuple(reflected["column_names"]) == columns
    command.upgrade(cfg, revision)
    assert _state(conn, indexes) == dict.fromkeys(indexes, True)
    assert _state(conn, replaced) == {}


def test_a_build_failed_behind_an_old_snapshot_is_replaced_on_rerun(
    migration_db, test_settings
):
    conn, cfg, _, pre_revision, revision, indexes = migration_db
    command.downgrade(cfg, pre_revision)
    # An old snapshot (a long report, an idle transaction) makes the concurrent
    # build wait; the revision's 5 s lock timeout then aborts it.
    holder = _connect(test_settings)
    holder.autocommit = False
    try:
        with holder.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            table = next(iter(indexes.values())).__table__
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table.name))
            )
        with pytest.raises(sa.exc.OperationalError):
            command.upgrade(cfg, revision)
    finally:
        holder.rollback()
        holder.close()

    assert _version(conn) == pre_revision
    assert False in _state(conn, indexes).values()  # an INVALID leftover

    command.upgrade(cfg, revision)

    assert _version(conn) == revision
    assert _state(conn, indexes) == dict.fromkeys(indexes, True)
