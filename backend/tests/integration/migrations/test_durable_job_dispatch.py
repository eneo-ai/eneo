from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

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
            cursor.execute(
                """
                EXPLAIN
                SELECT id
                FROM jobs
                WHERE status = 'queued'
                  AND dispatch_envelope IS NOT NULL
                  AND task IN ('upload_info_blob', 'transcription')
                  AND created_at <= now() - interval '5 minutes'
                  AND (
                    dispatch_attempted_at IS NULL
                    OR dispatch_attempted_at <= now() - interval '5 minutes'
                  )
                ORDER BY dispatch_attempted_at ASC NULLS FIRST, id ASC
                LIMIT 50
                FOR UPDATE SKIP LOCKED
                """
            )
            plan = "\n".join(str(row[0]) for row in cursor.fetchall())
        assert _INDEX in plan
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
