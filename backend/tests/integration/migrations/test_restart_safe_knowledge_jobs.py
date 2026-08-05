from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.jobs.job_repo import stale_in_progress_jobs_statement
from eneo.jobs.job_staging import terminal_staging_jobs_statement

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202607281600"
_REAPER_INDEX = "ix_jobs_knowledge_in_progress_reaper"
_CLEANUP_INDEX = "ix_jobs_staging_cleanup"


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
        username="restart_safe_jobs",
        password="restart_safe_jobs_password",
        dbname="restart_safe_jobs",
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


def _prepared_plan(
    connection: psycopg2.extensions.connection,
    *,
    name: str,
    statement: ClauseElement,
) -> str:
    compiled_query = statement.compile(
        dialect=postgresql.dialect(paramstyle="numeric_dollar"),
        compile_kwargs={"render_postcompile": True},
    )
    assert compiled_query.positiontup is not None
    values = [compiled_query.params[key] for key in compiled_query.positiontup]
    prepared_types = ", ".join(_prepared_type(value) for value in values)
    execute_params = ", ".join(["%s"] * len(values))
    with connection.cursor() as cursor:
        cursor.execute(f"PREPARE {name} ({prepared_types}) AS {compiled_query}")
        cursor.execute(f"EXPLAIN EXECUTE {name} ({execute_params})", values)
        return "\n".join(str(row[0]) for row in cursor.fetchall())


def test_restart_safe_knowledge_migration_round_trip_and_query_plans(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, "head")

    columns, indexes = _job_schema(database_url)
    assert "staging_cleaned_at" in columns
    assert {_REAPER_INDEX, _CLEANUP_INDEX} <= indexes

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off")
            cursor.execute("SET plan_cache_mode = force_generic_plan")
        reaper_plan = _prepared_plan(
            connection,
            name="restart_safe_reaper_plan",
            statement=stale_in_progress_jobs_statement(datetime.now(timezone.utc)),
        )
        cleanup_plan = _prepared_plan(
            connection,
            name="restart_safe_cleanup_plan",
            statement=terminal_staging_jobs_statement(),
        )
        assert _REAPER_INDEX in reaper_plan
        assert _CLEANUP_INDEX in cleanup_plan
    finally:
        connection.close()

    terminal_job_id = uuid4()
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
                try:
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            id, user_id, task, status, dispatch_envelope,
                            finished_at
                        )
                        VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb, now())
                        """,
                        (
                            str(terminal_job_id),
                            str(uuid4()),
                            "upload_info_blob",
                            "complete",
                            '{"version": 1}',
                        ),
                    )
                finally:
                    cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match=r"1 terminal envelope jobs"):
        command.downgrade(config, _PREVIOUS_REVISION)

    columns, indexes = _job_schema(database_url)
    assert "staging_cleaned_at" in columns
    assert {_REAPER_INDEX, _CLEANUP_INDEX} <= indexes

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET staging_cleaned_at = now()
                    WHERE id = %s::uuid
                    """,
                    (str(terminal_job_id),),
                )
    finally:
        connection.close()

    command.downgrade(config, _PREVIOUS_REVISION)
    columns, indexes = _job_schema(database_url)
    assert "staging_cleaned_at" not in columns
    assert _REAPER_INDEX not in indexes
    assert _CLEANUP_INDEX not in indexes

    command.upgrade(config, "head")
    columns, indexes = _job_schema(database_url)
    assert "staging_cleaned_at" in columns
    assert {_REAPER_INDEX, _CLEANUP_INDEX} <= indexes
