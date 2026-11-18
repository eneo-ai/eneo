"""Both deployed migration histories must reach the combined schema."""

from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from tests.integration.migrations.alembic_test_utils import (
    at_revision,
    current_revisions,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _has_column(cursor, table: str, column: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cursor.fetchone() is not None


# A fresh database, and each parent: develop's conversation times
# (202611091200) and the Flows branch's live transcript parts (202611101200).
@pytest.mark.parametrize("start", ["base", "202611091200", "202611101200"])
def test_fresh_database_and_each_parent_reach_combined_schema(test_settings, start):
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    with at_revision(cfg, start):
        command.upgrade(cfg, "head")
        with psycopg2.connect(
            test_settings.sync_database_url.replace("+psycopg2", "")
        ) as conn:
            assert current_revisions(conn) == {head}
            with conn.cursor() as cursor:
                assert _has_column(cursor, "sessions", "feedback_set_at")
                assert _has_column(
                    cursor, "flow_live_transcripts", "part_start_samples"
                )
                cursor.execute("SELECT to_regclass('public.retention_job_runs')")
                assert cursor.fetchone() == ("retention_job_runs",)
