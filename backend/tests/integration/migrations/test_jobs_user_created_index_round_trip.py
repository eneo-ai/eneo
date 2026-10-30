"""Round trip for 202610261000: the jobs poll's per-user index.

    pytest -m migration_isolation \
        tests/integration/migrations/test_jobs_user_created_index_round_trip.py
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610251100"
REVISION = "202610261000"
INDEX = "ix_jobs_user_created"
DEFINITION = f"CREATE INDEX {INDEX} ON public.jobs USING btree (user_id, created_at)"


def _alembic_cfg(database_url: str) -> Config:
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
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
    try:
        with at_revision(cfg, REVISION):
            yield conn, cfg
    finally:
        conn.close()


def _index(conn) -> tuple[str, bool, int] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_indexdef(indexrelid), indisvalid, indexrelid::int "
            "FROM pg_index WHERE indexrelid = to_regclass(%s)",
            (INDEX,),
        )
        return cursor.fetchone()


def _poll_plan_indexes(conn) -> set[str]:
    """Indexes the jobs poll's shape can use, with sequential scans forbidden."""
    with conn.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(
                "EXPLAIN (FORMAT JSON) SELECT * FROM jobs WHERE user_id = %s "
                "AND created_at >= now() - interval '7 days' ORDER BY created_at",
                (str(uuid4()),),
            )
            plan = cursor.fetchone()[0]
        finally:
            cursor.execute("ROLLBACK")
    plan = json.loads(plan) if isinstance(plan, str) else plan
    names: set[str] = set()
    pending: list[object] = [plan]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if isinstance(name := node.get("Index Name"), str):
                names.add(name)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return names


def test_upgrade_builds_a_valid_index_the_poll_can_use(round_trip_db):
    conn, _cfg = round_trip_db

    assert _index(conn)[:2] == (DEFINITION, True)
    assert INDEX in _poll_plan_indexes(conn)


def test_downgrade_drops_the_index_and_upgrade_restores_it(round_trip_db):
    conn, cfg = round_trip_db

    command.downgrade(cfg, PRE_REVISION)
    assert _index(conn) is None
    assert INDEX not in _poll_plan_indexes(conn)

    command.upgrade(cfg, REVISION)
    assert _index(conn)[:2] == (DEFINITION, True)


def test_rerun_rebuilds_an_invalid_leftover_and_keeps_a_valid_index(round_trip_db):
    conn, cfg = round_trip_db
    built = _index(conn)

    # A rerun over a valid index keeps it.
    command.stamp(cfg, PRE_REVISION)
    command.upgrade(cfg, REVISION)
    assert _index(conn) == built

    # An interrupted build leaves the index INVALID; the rerun rebuilds it.
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE pg_index SET indisvalid = false WHERE indexrelid = %s::regclass",
            (INDEX,),
        )
    command.stamp(cfg, PRE_REVISION)
    command.upgrade(cfg, REVISION)
    rebuilt = _index(conn)
    assert rebuilt[:2] == (DEFINITION, True)
    assert rebuilt[2] != built[2]
