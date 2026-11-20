from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from time import monotonic, sleep

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from eneo.apps.app_runs.app_run_dispatch import (
    interrupted_app_jobs,
    next_retryable_app_submission,
)
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand
from tests.integration.migrations.test_restart_safe_knowledge_jobs import _prepared_plan

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
            query.execute("SET enable_seqscan = off")
            query.execute("SET plan_cache_mode = force_generic_plan")
            now = datetime.now(timezone.utc)
            for name, statement in (
                ("app_interruption_scan", interrupted_app_jobs(now)),
                ("app_redispatch_scan", next_retryable_app_submission(now)),
            ):
                assert "ix_jobs_active_task_updated_id" in _prepared_plan(
                    connection, name=name, statement=statement
                )
