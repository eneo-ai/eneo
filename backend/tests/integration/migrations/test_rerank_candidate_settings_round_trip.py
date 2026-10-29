"""Round-trip test for the rerank candidate settings migration.

Verifies that ``202610221000`` adds ``candidate_factor`` and ``max_candidates``
to ``rerank_models`` with the defaults 5 and 100 for existing rows, enforces
the ranges, and removes both columns on downgrade.

Run alongside other migration round-trips:
    pytest -m migration_isolation \
        tests/integration/migrations/test_rerank_candidate_settings_round_trip.py -v
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610161000"
REVISION = "202610221000"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    """Override shared cleanup_database so schema revisions persist across
    downgrade/upgrade cycles within this module.
    """
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Override shared seed_default_models — this module seeds no data."""
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

    command.upgrade(cfg, REVISION)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        conn.close()


def _columns(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'rerank_models'"
        )
        return {row[0] for row in cur.fetchall()}


def _insert_row(conn, **settings) -> str:
    """A minimal rerank model row, without tenant or provider."""
    row_id = str(uuid4())
    columns = ["id", "name", "nickname", "family", "stability", "hosting", *settings]
    values = [row_id, "rerank", f"Rerank {row_id[:8]}", "cohere", "stable", "eu"]
    values += list(settings.values())
    placeholders = ", ".join(["%s"] * len(values))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO rerank_models ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
    return row_id


def _settings(conn, row_id: str) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT candidate_factor, max_candidates FROM rerank_models WHERE id = %s",
            (row_id,),
        )
        return cur.fetchone()


class TestRerankCandidateSettingsRoundTrip:
    def test_existing_rows_get_the_defaults(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        command.downgrade(cfg, PRE_REVISION)
        row_id = _insert_row(conn)
        command.upgrade(cfg, REVISION)

        assert _settings(conn, row_id) == (5, 100)

    def test_values_outside_the_ranges_are_refused(self, round_trip_db):
        conn = round_trip_db["conn"]

        for settings in (
            {"candidate_factor": 0},
            {"candidate_factor": 21},
            {"max_candidates": 0},
            {"max_candidates": 1001},
        ):
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_row(conn, **settings)

        assert _settings(
            conn, _insert_row(conn, candidate_factor=20, max_candidates=1000)
        ) == (
            20,
            1000,
        )

    def test_downgrade_removes_the_columns(self, round_trip_db):
        conn = round_trip_db["conn"]
        cfg = round_trip_db["cfg"]

        assert {"candidate_factor", "max_candidates"} <= _columns(conn)
        command.downgrade(cfg, PRE_REVISION)
        assert not {"candidate_factor", "max_candidates"} & _columns(conn)
        command.upgrade(cfg, REVISION)
        assert {"candidate_factor", "max_candidates"} <= _columns(conn)
