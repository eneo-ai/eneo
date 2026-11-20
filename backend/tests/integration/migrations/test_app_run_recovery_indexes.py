from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from time import monotonic, sleep

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202611091200"
_REVISION = "202611190900"
_MIGRATION_APPLICATION = "app-run-recovery-index-test"
_INDEXES = {"ix_jobs_active_task_updated_id", "ix_app_runs_job_id"}


def test_recovery_indexes_wait_for_an_in_flight_job_write():
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url()
        command.upgrade(expand._alembic_config(url), _PREVIOUS_REVISION)
        migration = expand._alembic_config(
            f"{url}?application_name={_MIGRATION_APPLICATION}"
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            with closing(expand._connect(url)) as writer, writer.cursor() as write:
                # An UPDATE holds this table lock until the worker commits.
                write.execute("LOCK TABLE jobs IN ROW EXCLUSIVE MODE")
                write.execute("SELECT pg_backend_pid()")
                (writer_pid,) = write.fetchone()

                upgrade = executor.submit(command.upgrade, migration, _REVISION)
                with (
                    closing(expand._connect(url)) as monitor,
                    monitor.cursor() as query,
                ):
                    monitor.autocommit = True
                    deadline = monotonic() + 15
                    while monotonic() < deadline:
                        if upgrade.done():
                            upgrade.result()
                            pytest.fail(
                                "index build finished before the writer released its lock"
                            )
                        query.execute(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE application_name = %s AND %s = ANY(pg_blocking_pids(pid)))",
                            (_MIGRATION_APPLICATION, writer_pid),
                        )
                        if query.fetchone() == (True,):
                            break
                        sleep(0.05)
                    else:
                        pytest.fail("index build never waited for the job writer")

                    query.execute("SET lock_timeout = '1s'")
                    query.execute("UPDATE jobs SET status = status WHERE false")

                # Simulate a job holding the write open past the old five-second limit.
                with pytest.raises(TimeoutError):
                    upgrade.result(timeout=6)
                writer.commit()
            upgrade.result(timeout=15)

        with closing(expand._connect(url)) as connection, connection.cursor() as query:
            query.execute(
                "SELECT indexrelid::regclass::text FROM pg_index "
                "WHERE indexrelid::regclass::text = ANY(%s) AND indisvalid AND indisready",
                (list(_INDEXES),),
            )
            assert {name for (name,) in query.fetchall()} == _INDEXES
