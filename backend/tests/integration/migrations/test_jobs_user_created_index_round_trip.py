"""Round trip for 202611030830: the jobs poll's per-user index.

On the Flows branch it also proves the merge that replaced the branch's own
copy of this index (202610261000): one head, and a Flows database keeps one
index through 202611031100.

    pytest -m migration_isolation \
        tests/integration/migrations/test_jobs_user_created_index_round_trip.py
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202611021100"
REVISION = "202611030830"
INDEX = "ix_jobs_user_created"
DEFINITION = f"CREATE INDEX {INDEX} ON public.jobs USING btree (user_id, created_at)"
FLOWS_HEAD = "202611021200"  # origin/feat/flows-core-integration before the merge
HEAD = "202611031100"
# Develop's two migrations after 202611021100, which the Flows head never had.
DEVELOP_BRANCH_DOWN = "202611031000@202611021100"
# What the branch's 202610261000 ran.
BRANCH_DDL = (
    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON jobs (user_id, created_at)"
)


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def encryption_service() -> Generator[None, None, None]:
    yield


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_db():
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="jobs_user_created",
        password="jobs_user_created_password",
        dbname="jobs_user_created",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, REVISION)
        conn = psycopg2.connect(database_url.replace("+psycopg2", ""))
        conn.autocommit = True
        try:
            yield conn, config
        finally:
            conn.close()


@pytest.fixture
def round_trip_db(migrated_db):
    """Each test starts and ends at REVISION."""
    _conn, config = migrated_db
    yield migrated_db
    command.upgrade(config, REVISION)


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
    conn, _config = round_trip_db

    assert _index(conn)[:2] == (DEFINITION, True)
    assert INDEX in _poll_plan_indexes(conn)


def test_downgrade_drops_the_index_and_upgrade_restores_it(round_trip_db):
    conn, config = round_trip_db

    command.downgrade(config, PRE_REVISION)
    assert _index(conn) is None
    assert INDEX not in _poll_plan_indexes(conn)

    command.upgrade(config, REVISION)
    assert _index(conn)[:2] == (DEFINITION, True)


def test_rerun_rebuilds_an_invalid_leftover_and_keeps_a_valid_index(round_trip_db):
    conn, config = round_trip_db
    built = _index(conn)

    # A rerun over a valid index keeps it.
    command.stamp(config, PRE_REVISION)
    command.upgrade(config, REVISION)
    assert _index(conn) == built

    # An interrupted build leaves the index INVALID; the rerun rebuilds it.
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE pg_index SET indisvalid = false WHERE indexrelid = %s::regclass",
            (INDEX,),
        )
    command.stamp(config, PRE_REVISION)
    command.upgrade(config, REVISION)
    rebuilt = _index(conn)
    assert rebuilt[:2] == (DEFINITION, True)
    assert rebuilt[2] != built[2]


def _stamps(conn) -> set[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        return {row[0] for row in cursor.fetchall()}


def _jobs_poll_indexes(conn) -> list[tuple[str, bool]]:
    """Every index on jobs over exactly (user_id, created_at), whatever its name."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_indexdef(i.indexrelid), i.indisvalid FROM pg_index i "
            "WHERE i.indrelid = 'jobs'::regclass "
            "AND pg_get_indexdef(i.indexrelid) LIKE '%%(user_id, created_at)'"
        )
        return cursor.fetchall()


def test_the_history_has_one_head(migrated_db):
    _conn, config = migrated_db

    assert ScriptDirectory.from_config(config).get_heads() == [HEAD]


def test_a_fresh_database_migrates_to_head_with_the_index(migrated_db):
    conn, config = migrated_db

    command.upgrade(config, "head")

    assert _stamps(conn) == {HEAD}
    assert _jobs_poll_indexes(conn) == [(DEFINITION, True)]


def _down_to_the_flows_head(config) -> None:
    """The merge goes, then develop's statistics and index migrations."""
    command.downgrade(config, FLOWS_HEAD)
    command.downgrade(config, DEVELOP_BRANCH_DOWN)


def test_the_merge_revisions_round_trip(migrated_db):
    conn, config = migrated_db
    command.upgrade(config, "head")

    _down_to_the_flows_head(config)
    assert _stamps(conn) == {FLOWS_HEAD}
    assert _jobs_poll_indexes(conn) == []

    command.upgrade(config, "head")
    assert _stamps(conn) == {HEAD}
    assert _jobs_poll_indexes(conn) == [(DEFINITION, True)]


def test_a_flows_database_with_the_branch_index_keeps_one_copy(migrated_db):
    """Alexander's case: at the Flows head, with the index the branch's
    202610261000 built, the upgrade keeps that index and adds none."""
    conn, config = migrated_db
    command.upgrade(config, "head")
    _down_to_the_flows_head(config)
    assert _stamps(conn) == {FLOWS_HEAD}
    with conn.cursor() as cursor:
        cursor.execute(BRANCH_DDL)
        cursor.execute("SELECT to_regclass(%s)::oid::int", (INDEX,))
        built = cursor.fetchone()[0]

    command.upgrade(config, "head")

    assert _stamps(conn) == {HEAD}
    assert _jobs_poll_indexes(conn) == [(DEFINITION, True)]
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)::oid::int", (INDEX,))
        assert cursor.fetchone()[0] == built
