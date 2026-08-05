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

_PREVIOUS_REVISION = "202607301200"
_REVISION = "202607311000"


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
        username="knowledge_originals",
        password="knowledge_originals_password",
        dbname="knowledge_originals",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        yield database_url, _alembic_config(database_url)


def _connection(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _reference_schema(database_url: str) -> tuple[set[str], tuple[str, ...]]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {
            str(column["name"])
            for column in inspector.get_columns("info_blob_content_references")
        }
        primary_key = tuple(
            str(column)
            for column in inspector.get_pk_constraint("info_blob_content_references")[
                "constrained_columns"
            ]
        )
        return columns, primary_key
    finally:
        engine.dispose()


def _insert_reference_drift(
    database_url: str,
    *,
    original_filename: str | None = None,
) -> None:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE info_blob_content_references DISABLE TRIGGER ALL"
            )
            try:
                if original_filename is None:
                    cursor.execute(
                        """
                        INSERT INTO info_blob_content_references (
                            info_blob_id, content_id, variant
                        )
                        VALUES (%s::uuid, %s::uuid, 'extracted_text')
                        """,
                        (str(uuid4()), str(uuid4())),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO info_blob_content_references (
                            info_blob_id, content_id, original_filename
                        )
                        VALUES (%s::uuid, %s::uuid, %s)
                        """,
                        (str(uuid4()), str(uuid4()), original_filename),
                    )
            finally:
                cursor.execute(
                    "ALTER TABLE info_blob_content_references ENABLE TRIGGER ALL"
                )


def _insert_knowledge_job(
    database_url: str,
    *,
    version: int,
    status: str,
) -> None:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs (
                        id, user_id, task, name, status, dispatch_envelope
                    )
                    VALUES (
                        %s::uuid, %s::uuid, 'upload_info_blob', 'document.txt',
                        %s, jsonb_build_object('version', %s)
                    )
                    """,
                    (str(uuid4()), str(uuid4()), status, version),
                )
            finally:
                cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")


def _clear_drift(database_url: str) -> None:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE info_blob_content_references DISABLE TRIGGER ALL"
            )
            cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
            try:
                cursor.execute("DELETE FROM info_blob_content_references")
                cursor.execute(
                    """
                    DELETE FROM jobs
                    WHERE task IN ('upload_info_blob', 'transcription')
                    """
                )
            finally:
                cursor.execute(
                    "ALTER TABLE info_blob_content_references ENABLE TRIGGER ALL"
                )
                cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")


def test_knowledge_original_reference_migration_guards_and_round_trip(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _PREVIOUS_REVISION)

    _insert_reference_drift(database_url)
    with pytest.raises(RuntimeError, match="unexpected existing reference"):
        command.upgrade(config, _REVISION)
    _clear_drift(database_url)

    _insert_knowledge_job(database_url, version=1, status="queued")
    with pytest.raises(RuntimeError, match="active legacy knowledge job"):
        command.upgrade(config, _REVISION)
    _clear_drift(database_url)

    command.upgrade(config, _REVISION)
    columns, primary_key = _reference_schema(database_url)
    assert columns == {
        "info_blob_id",
        "content_id",
        "original_filename",
        "created_at",
        "updated_at",
    }
    assert primary_key == ("info_blob_id",)

    _insert_reference_drift(database_url, original_filename="document.txt")
    with pytest.raises(RuntimeError, match="knowledge original reference"):
        command.downgrade(config, _PREVIOUS_REVISION)
    _clear_drift(database_url)

    _insert_knowledge_job(database_url, version=2, status="in progress")
    with pytest.raises(RuntimeError, match="active v2 knowledge job"):
        command.downgrade(config, _PREVIOUS_REVISION)
    _clear_drift(database_url)

    command.downgrade(config, _PREVIOUS_REVISION)
    columns, primary_key = _reference_schema(database_url)
    assert columns == {
        "info_blob_id",
        "content_id",
        "variant",
        "created_at",
        "updated_at",
    }
    assert primary_key == ("info_blob_id", "variant")

    command.upgrade(config, _REVISION)
