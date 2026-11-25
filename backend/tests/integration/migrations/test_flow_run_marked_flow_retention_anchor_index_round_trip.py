"""Round trip for 202611241100: the marked runs' per-flow retention anchor index.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_run_marked_flow_retention_anchor_index_round_trip.py

After the revision the database holds the index exactly as the ORM declares
it; a downgrade drops it, and a rerun after an interrupted build replaces an
INVALID leftover.
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

PRE_REVISION = "202611241000"
REVISION = "202611241100"
INDEX = "ix_flow_runs_marked_flow_retention_anchor"


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def round_trip_db(test_settings):
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
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


def _declared_ddl() -> str:
    index = next(i for i in FlowRuns.__table__.indexes if i.name == INDEX)
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def _index(conn) -> tuple[str, bool, int] | None:
    """The index's definition, validity and oid, or None without it."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_indexdef(indexrelid), indisvalid, indexrelid::int "
            "FROM pg_index WHERE indexrelid = to_regclass(%s)",
            (INDEX,),
        )
        return cursor.fetchone()


def _assert_upgraded(conn, engine) -> None:
    found = _index(conn)
    assert found is not None
    ddl, valid, _ = found
    assert valid
    assert ddl_text(ddl) == ddl_text(_declared_ddl())
    assert index_drift(engine) == {}


def test_upgrade_matches_the_orm(round_trip_db):
    conn, _cfg, engine = round_trip_db
    _assert_upgraded(conn, engine)


def test_downgrade_drops_the_index_and_upgrade_builds_it_again(round_trip_db):
    conn, cfg, engine = round_trip_db

    command.downgrade(cfg, PRE_REVISION)
    assert _index(conn) is None
    assert index_drift(engine, introduced_later={INDEX}) == {}

    command.upgrade(cfg, REVISION)
    _assert_upgraded(conn, engine)


def test_rerun_after_an_interrupted_upgrade_rebuilds_the_invalid_index(
    round_trip_db,
):
    conn, cfg, engine = round_trip_db
    command.downgrade(cfg, PRE_REVISION)
    with conn.cursor() as cursor:
        cursor.execute(
            _declared_ddl().replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY")
        )
        # What an interrupted CREATE INDEX CONCURRENTLY leaves behind.
        cursor.execute(
            "UPDATE pg_index SET indisvalid = false WHERE indexrelid = %s::regclass",
            (INDEX,),
        )
    before = _index(conn)
    assert before is not None and not before[1]

    command.upgrade(cfg, REVISION)
    after = _index(conn)
    _assert_upgraded(conn, engine)
    assert after is not None and after[2] != before[2]
