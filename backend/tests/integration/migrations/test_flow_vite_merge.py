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


@pytest.mark.parametrize("start", ["base", "202610281000", "202610291900"])
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
                cursor.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'flow_runs' "
                    "AND column_name = 'run_date'"
                )
                assert cursor.fetchone() == ("date",)
                cursor.execute(
                    "SELECT to_regclass('public.skill_revision_dependencies')"
                )
                assert cursor.fetchone() == ("skill_revision_dependencies",)
                cursor.execute(
                    "SELECT indisvalid FROM pg_index "
                    "WHERE indexrelid = to_regclass('public.ix_jobs_user_created')"
                )
                assert cursor.fetchone() == (True,)
