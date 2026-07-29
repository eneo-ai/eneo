from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.jobs.durable_dispatch import stale_dispatch_statement

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202607281340"
_INDEX = "ix_jobs_durable_dispatch"


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
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="durable_dispatch",
        password="durable_dispatch_password",
        dbname="durable_dispatch",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _job_schema(database_url: str) -> tuple[set[str], set[str]]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {str(column["name"]) for column in inspector.get_columns("jobs")}
        indexes = {str(index["name"]) for index in inspector.get_indexes("jobs")}
        return columns, indexes
    finally:
        engine.dispose()


def _prepared_type(value: object) -> str:
    if isinstance(value, datetime):
        return "timestamptz"
    if isinstance(value, str):
        return "text"
    if isinstance(value, int):
        return "integer"
    raise TypeError(f"Unsupported prepared query value: {type(value).__name__}")


def _wait_for_downgrade_barrier(connection: psycopg2.extensions.connection) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock'
                      AND wait_event = 'advisory'
                      AND query LIKE 'DROP INDEX%ix_jobs_durable_dispatch%'
                )
                """
            )
            if cursor.fetchone() == (True,):
                return
        sleep(0.05)
    raise AssertionError("Downgrade did not reach the index-drop barrier")


def test_durable_dispatch_migration_round_trip_and_query_plan(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database

    command.upgrade(config, "head")
    columns, indexes = _job_schema(database_url)
    assert {"dispatch_envelope", "dispatch_attempted_at"} <= columns
    assert _INDEX in indexes

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off")
            cursor.execute("SET plan_cache_mode = force_generic_plan")
            production_query = stale_dispatch_statement(datetime.now(timezone.utc))
            compiled_query = production_query.compile(
                dialect=postgresql.dialect(paramstyle="numeric_dollar"),
                compile_kwargs={"render_postcompile": True},
            )
            assert compiled_query.positiontup is not None
            values = [
                compiled_query.params[name] for name in compiled_query.positiontup
            ]
            prepared_types = ", ".join(_prepared_type(value) for value in values)
            cursor.execute(
                f"PREPARE durable_dispatch_plan ({prepared_types}) AS {compiled_query}"
            )
            execute_params = ", ".join(["%s"] * len(values))
            cursor.execute(
                f"EXPLAIN EXECUTE durable_dispatch_plan ({execute_params})",
                values,
            )
            plan = "\n".join(str(row[0]) for row in cursor.fetchall())
        assert _INDEX in plan
    finally:
        connection.close()

    pending_job_id = uuid4()
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
                try:
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            id, user_id, task, status, dispatch_envelope
                        )
                        VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb)
                        """,
                        (
                            str(pending_job_id),
                            str(uuid4()),
                            "upload_info_blob",
                            "queued",
                            '{"version": 1}',
                        ),
                    )
                finally:
                    cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
    finally:
        connection.close()

    with pytest.raises(
        RuntimeError,
        match=r"1.*[Dd]rain.*explicitly fail",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)

    columns, indexes = _job_schema(database_url)
    assert "dispatch_envelope" in columns
    assert _INDEX in indexes

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT dispatch_envelope FROM jobs WHERE id = %s::uuid",
                    (str(pending_job_id),),
                )
                assert cursor.fetchone() == ({"version": 1},)
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', staging_cleaned_at = now()
                    WHERE id = %s::uuid
                    """,
                    (str(pending_job_id),),
                )
    finally:
        connection.close()

    command.downgrade(config, _PREVIOUS_REVISION)
    columns, indexes = _job_schema(database_url)
    assert "dispatch_envelope" not in columns
    assert "dispatch_attempted_at" not in columns
    assert _INDEX not in indexes

    command.upgrade(config, "head")
    columns, indexes = _job_schema(database_url)
    assert {"dispatch_envelope", "dispatch_attempted_at"} <= columns
    assert _INDEX in indexes


def test_downgrade_excludes_a_concurrent_durable_insert(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    sync_database_url = database_url.replace("+psycopg2", "")
    command.upgrade(config, "head")
    writer_job_id = uuid4()
    barrier_key = 2_026_072_816

    barrier = psycopg2.connect(sync_database_url)
    barrier.autocommit = True
    try:
        with barrier.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs
                SET staging_cleaned_at = now()
                WHERE dispatch_envelope IS NOT NULL
                  AND status IN ('complete', 'failed')
                  AND staging_cleaned_at IS NULL
                """
            )
            cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
            cursor.execute("SELECT pg_advisory_lock(%s)", (barrier_key,))
            cursor.execute(
                f"""
                CREATE FUNCTION durable_dispatch_downgrade_barrier()
                RETURNS event_trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF tg_tag = 'DROP INDEX'
                       AND current_query() LIKE '%ix_jobs_durable_dispatch%' THEN
                        PERFORM pg_advisory_lock({barrier_key});
                        PERFORM pg_advisory_unlock({barrier_key});
                    END IF;
                END
                $$;
                CREATE EVENT TRIGGER durable_dispatch_downgrade_barrier
                ON ddl_command_start
                EXECUTE FUNCTION durable_dispatch_downgrade_barrier();
                """
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            downgrade = executor.submit(
                command.downgrade,
                config,
                _PREVIOUS_REVISION,
            )
            try:
                _wait_for_downgrade_barrier(barrier)

                writer_error: Exception | None = None
                writer = psycopg2.connect(sync_database_url)
                try:
                    with writer:
                        with writer.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '1s'")
                            cursor.execute(
                                """
                                INSERT INTO jobs (
                                    id, user_id, task, status, dispatch_envelope
                                )
                                VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb)
                                """,
                                (
                                    str(writer_job_id),
                                    str(uuid4()),
                                    "upload_info_blob",
                                    "queued",
                                    '{"version": 1}',
                                ),
                            )
                except Exception as exc:
                    writer_error = exc
                finally:
                    writer.close()
            finally:
                with barrier.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (barrier_key,))
            downgrade_error = downgrade.exception(timeout=10)
    finally:
        with barrier.cursor() as cursor:
            cursor.execute(
                "DROP EVENT TRIGGER IF EXISTS durable_dispatch_downgrade_barrier"
            )
            cursor.execute(
                "DROP FUNCTION IF EXISTS durable_dispatch_downgrade_barrier()"
            )
            cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
            cursor.execute("SELECT pg_advisory_unlock(%s)", (barrier_key,))
        barrier.close()

    command.upgrade(config, "head")
    assert downgrade_error is None
    assert isinstance(writer_error, psycopg2.errors.LockNotAvailable)

    connection = psycopg2.connect(sync_database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM jobs WHERE id = %s::uuid",
                (str(writer_job_id),),
            )
            assert cursor.fetchone() == (0,)
    finally:
        connection.close()
