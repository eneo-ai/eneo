"""Round trip for 202610191005: speaker names beside transcript corrections.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_transcript_speaker_names_round_trip.py
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610151000"
REVISION = "202610191005"
TABLES = ("flow_transcript_corrections", "flow_transcript_correction_revisions")
STEP_ID = "5a1e0000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the schema revision across the cycle within this module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _speaker_names_columns(conn) -> dict[str, tuple[str, str, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE column_name = 'speaker_names' AND table_name = ANY(%s)",
            (list(TABLES),),
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}


def _store_a_correction_set(conn) -> None:
    # The set's run, flow and editor are not what is tested: without the
    # foreign-key triggers the row needs none. CHECKs still apply.
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        cur.execute(
            "INSERT INTO flow_transcript_corrections (tenant_id, flow_id, "
            "flow_run_id, step_id, occurrences_json, segments_hash, "
            "edited_by_principal_type, edited_by_user_id) VALUES "
            "(gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), "
            "%s, '[]', repeat('a', 64), 'user', gen_random_uuid())",
            (STEP_ID,),
        )
        cur.execute("SET session_replication_role = DEFAULT")


def test_speaker_names_columns_come_and_go_with_the_revision(test_settings):
    # Kills the mutants where either table lacks the column, where it is
    # nullable or without the '{}' default an existing set reads, and where
    # the downgrade leaves a column behind.
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
    expected = {table: ("jsonb", "NO", "'{}'::jsonb") for table in TABLES}
    try:
        # A fresh database has no schema yet; one at head is past the revision.
        with at_revision(cfg, PRE_REVISION):
            try:
                assert _speaker_names_columns(conn) == {}
                _store_a_correction_set(conn)

                command.upgrade(cfg, REVISION)
                assert _speaker_names_columns(conn) == expected
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT speaker_names FROM flow_transcript_corrections "
                        "WHERE step_id = %s",
                        (STEP_ID,),
                    )
                    assert cur.fetchall() == [({},)]

                command.downgrade(cfg, PRE_REVISION)
                assert _speaker_names_columns(conn) == {}

                command.upgrade(cfg, REVISION)
                assert _speaker_names_columns(conn) == expected
            finally:
                with conn.cursor() as cur:
                    cur.execute("SET session_replication_role = replica")
                    cur.execute(
                        "DELETE FROM flow_transcript_corrections WHERE step_id = %s",
                        (STEP_ID,),
                    )
                    cur.execute("SET session_replication_role = DEFAULT")
    finally:
        conn.close()
