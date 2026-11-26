from contextlib import closing

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_SHARED_PARENT = "202610261200"
_RELEASE = "202611201300"
_DEVELOP_INDEXES = "202611190900"
_MERGE = "202611261000"


def _index_ids(cursor):
    cursor.execute(
        "SELECT indexrelid FROM pg_index WHERE indexrelid IN "
        "('ix_jobs_active_task_updated_id'::regclass, 'ix_app_runs_job_id'::regclass) "
        "AND indisvalid AND indisready ORDER BY indexrelid"
    )
    return cursor.fetchall()


@pytest.mark.parametrize(
    ("start", "index_revision"),
    [
        (_RELEASE, _RELEASE),
        (_DEVELOP_INDEXES, _DEVELOP_INDEXES),
    ],
)
def test_upgrade_preserves_indexes_and_applies_missing_revisions(start, index_revision):
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        config = expand._alembic_config(url)
        command.upgrade(config, start)
        with closing(expand._connect(url)) as db, db.cursor() as cursor:
            db.autocommit = True
            indexes = _index_ids(cursor)
            assert len(indexes) == 2
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE "
                "table_name = 'sessions' AND column_name = 'feedback_set_at')"
            )
            assert cursor.fetchone() == (start != _RELEASE,)

            command.upgrade(config, _MERGE)
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchall() == [(_MERGE,)]
            cursor.execute("SELECT name_set_at, feedback_set_at FROM sessions LIMIT 0")
            assert _index_ids(cursor) == indexes

            # Split the merge, then downgrade only one side. The other side
            # still owns the indexes and must continue using the same objects.
            command.downgrade(config, index_revision)
            command.downgrade(config, f"{index_revision}@-1")
            assert _index_ids(cursor) == indexes

            command.downgrade(config, _SHARED_PARENT)
            cursor.execute(
                "SELECT to_regclass('ix_jobs_active_task_updated_id'), "
                "to_regclass('ix_app_runs_job_id')"
            )
            assert cursor.fetchone() == (None, None)
            command.upgrade(config, _MERGE)
            assert len(_index_ids(cursor)) == 2
