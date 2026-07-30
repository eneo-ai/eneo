from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202607301100"


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
        username="job_failure_codes",
        password="job_failure_codes_password",
        dbname="job_failure_codes",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _job_columns(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return {str(column["name"]) for column in inspect(engine).get_columns("jobs")}
    finally:
        engine.dispose()


def test_job_failure_code_migration_preserves_legacy_failure_prose(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _PREVIOUS_REVISION)

    job_id = uuid4()
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
                try:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, user_id, task, status, result_location)
                        VALUES (%s::uuid, %s::uuid, %s, %s, %s)
                        """,
                        (
                            str(job_id),
                            str(uuid4()),
                            "upload_info_blob",
                            "failed",
                            "legacy internal detail",
                        ),
                    )
                finally:
                    cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
    finally:
        connection.close()

    command.upgrade(config, "head")
    assert "failure_code" in _job_columns(database_url)

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_location, failure_code
                FROM jobs
                WHERE id = %s::uuid
                """,
                (str(job_id),),
            )
            assert cursor.fetchone() == ("legacy internal detail", None)
    finally:
        connection.close()

    command.downgrade(config, _PREVIOUS_REVISION)
    assert "failure_code" not in _job_columns(database_url)

    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_location FROM jobs WHERE id = %s::uuid",
                (str(job_id),),
            )
            assert cursor.fetchone() == ("legacy internal detail",)
    finally:
        connection.close()

    command.upgrade(config, "head")
    assert "failure_code" in _job_columns(database_url)
