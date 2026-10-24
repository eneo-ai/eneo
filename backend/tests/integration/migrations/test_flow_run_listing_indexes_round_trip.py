"""Round trip for 202610241000: the run list indexes replace ix_flow_runs_flow_id.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_run_listing_indexes_round_trip.py

After the revision the ORM declares exactly what the database holds: the
reflected shape of every flows-owned index matches, and each new index's
definition text (expressions, sort direction, INCLUDE, predicate) equals the
ORM's DDL. A rerun after an interrupted upgrade rebuilds only an INVALID
leftover and keeps the indexes already built.
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from alembic import command
from alembic.config import Config
from eneo.database.tables.flow_tables import FlowRuns
from tests.integration.migrations.alembic_test_utils import at_revision
from tests.integration.migrations.flow_index_drift import ddl_text, index_drift

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610231100"
REVISION = "202610241000"
NEW_INDEXES = (
    "ix_flow_runs_flow_listing",
    "ix_flow_runs_flow_user_listing",
    "ix_flow_runs_flow_service_listing",
)
REPLACED_INDEX = "ix_flow_runs_flow_id"
REPLACED_DEFINITION = f"CREATE INDEX {REPLACED_INDEX} ON flow_runs (flow_id)"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
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
def round_trip_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        with at_revision(cfg, REVISION):
            yield conn, cfg, engine
    finally:
        engine.dispose()
        conn.close()


def _declared_ddl(name: str) -> str:
    index = next(i for i in FlowRuns.__table__.indexes if i.name == name)
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def _flow_run_indexes(conn) -> dict[str, tuple[str, bool, int]]:
    """Each flow_runs index by name: its definition, validity and oid."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, pg_get_indexdef(i.indexrelid), i.indisvalid, "
            "i.indexrelid::int FROM pg_index i JOIN pg_class c "
            "ON c.oid = i.indexrelid WHERE i.indrelid = 'flow_runs'::regclass"
        )
        return {name: (ddl, valid, oid) for name, ddl, valid, oid in cursor.fetchall()}


def _assert_upgraded(conn, engine) -> None:
    indexes = _flow_run_indexes(conn)
    assert REPLACED_INDEX not in indexes
    for name in NEW_INDEXES:
        ddl, valid, _ = indexes[name]
        assert valid, name
        assert ddl_text(ddl) == ddl_text(_declared_ddl(name))
    assert all(valid for _, valid, _ in indexes.values())
    assert index_drift(engine) == {}


def _invalidate(conn, name: str) -> None:
    """What an interrupted CREATE INDEX CONCURRENTLY leaves behind."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE pg_index SET indisvalid = false WHERE indexrelid = %s::regclass",
            (name,),
        )


def test_upgrade_matches_the_orm_and_drops_the_flow_id_index(round_trip_db):
    conn, _cfg, engine = round_trip_db
    _assert_upgraded(conn, engine)


def test_downgrade_restores_the_flow_id_index_and_upgrade_replaces_it(
    round_trip_db,
):
    conn, cfg, engine = round_trip_db

    command.downgrade(cfg, PRE_REVISION)
    indexes = _flow_run_indexes(conn)
    assert not set(NEW_INDEXES) & indexes.keys()
    ddl, valid, _ = indexes[REPLACED_INDEX]
    assert valid
    assert ddl_text(ddl) == ddl_text(REPLACED_DEFINITION)

    command.upgrade(cfg, REVISION)
    _assert_upgraded(conn, engine)


def test_rerun_after_an_interrupted_upgrade_rebuilds_only_the_invalid_index(
    round_trip_db,
):
    conn, cfg, engine = round_trip_db
    # Interrupted while building the second index: the first is built, the
    # second is INVALID, the third and the drop never ran.
    command.downgrade(cfg, PRE_REVISION)
    with conn.cursor() as cursor:
        for name in NEW_INDEXES[:2]:
            cursor.execute(
                _declared_ddl(name).replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY")
            )
    _invalidate(conn, NEW_INDEXES[1])
    before = _flow_run_indexes(conn)

    command.upgrade(cfg, REVISION)
    after = _flow_run_indexes(conn)
    _assert_upgraded(conn, engine)
    assert after[NEW_INDEXES[0]][2] == before[NEW_INDEXES[0]][2]
    assert after[NEW_INDEXES[1]][2] != before[NEW_INDEXES[1]][2]


def test_rerun_after_an_interrupted_downgrade_rebuilds_the_flow_id_index(
    round_trip_db,
):
    conn, cfg, _engine = round_trip_db
    with conn.cursor() as cursor:
        cursor.execute(
            REPLACED_DEFINITION.replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY")
        )
    _invalidate(conn, REPLACED_INDEX)

    command.downgrade(cfg, PRE_REVISION)
    indexes = _flow_run_indexes(conn)
    assert indexes[REPLACED_INDEX][1]
    assert not set(NEW_INDEXES) & indexes.keys()
    assert all(valid for _, valid, _ in indexes.values())
