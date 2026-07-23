"""PostgreSQL migration contract for the measured Flow run job index."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607230130_review_actor_delete"
MIGRATION_REVISION = "202607232300_flow_run_job_index"
INDEX_NAME = "ix_flow_runs_job_id"


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
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
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
) -> tuple[bool, bool, bool, bool, str, tuple[str, ...]] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indisunique,
                index_metadata.indpred IS NULL,
                access_method.amname,
                array_agg(attribute_row.attname ORDER BY index_key.ordinality)
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
            JOIN unnest(index_metadata.indkey)
              WITH ORDINALITY AS index_key(attnum, ordinality)
              ON true
            JOIN pg_attribute AS attribute_row
              ON attribute_row.attrelid = table_row.oid
             AND attribute_row.attnum = index_key.attnum
            WHERE namespace_row.nspname = 'public'
              AND table_namespace_row.nspname = 'public'
              AND table_row.relname = 'flow_runs'
              AND index_row.relname = %s
            GROUP BY
                index_metadata.indisvalid,
                index_metadata.indisready,
                index_metadata.indisunique,
                index_metadata.indpred,
                access_method.amname
            """,
            (INDEX_NAME,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3], row[4], tuple(row[5])


def _assert_index_present(conn: PsycopgConnection) -> None:
    assert _index_metadata(conn) == (True, True, False, True, "btree", ("job_id",))


def test_upgrade_downgrade_and_reupgrade_restore_job_index(
    fresh_chain_db: tuple[PsycopgConnection, Config],
) -> None:
    conn, cfg = fresh_chain_db

    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _index_metadata(conn) is None

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_index_present(conn)

    command.downgrade(cfg, PRIOR_REVISION)
    assert current_revisions(conn) == {PRIOR_REVISION}
    assert _index_metadata(conn) is None

    command.upgrade(cfg, MIGRATION_REVISION)
    assert current_revisions(conn) == {MIGRATION_REVISION}
    _assert_index_present(conn)
