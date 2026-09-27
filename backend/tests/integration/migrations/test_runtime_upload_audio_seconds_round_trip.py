"""Round trip for 202609271200: the runtime upload's measured audio length.

    pytest -m migration_isolation \
        tests/integration/migrations/test_runtime_upload_audio_seconds_round_trip.py
"""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202609241200"
REVISION = "202609271200"


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the schema revision across the cycle within this module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _columns(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'flow_runtime_uploaded_files'"
        )
        return {row[0] for row in cur.fetchall()}


def test_audio_seconds_column_upgrades_and_downgrades(test_settings):
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
    try:
        command.upgrade(cfg, REVISION)
        assert "audio_seconds" in _columns(conn)

        command.downgrade(cfg, PRE_REVISION)
        assert "audio_seconds" not in _columns(conn)

        command.upgrade(cfg, REVISION)
        assert "audio_seconds" in _columns(conn)
    finally:
        command.upgrade(cfg, "head")
        conn.close()
