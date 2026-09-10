from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import ProgrammingError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_PREVIOUS_REVISION = "202607301100"
_FAILURE_CODE_REVISION = "202607301200"
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
    task: Literal["upload_info_blob", "transcription"] = "upload_info_blob",
    version: int | None,
    status: str,
    result_location: str | None = None,
) -> UUID:
    job_id = uuid4()
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE jobs DISABLE TRIGGER ALL")
            try:
                cursor.execute(
                    """
                    INSERT INTO jobs (
                        id, user_id, task, name, status, result_location,
                        dispatch_envelope
                    )
                    VALUES (
                        %s::uuid, %s::uuid, %s, 'legacy knowledge job', %s, %s,
                        CASE
                            WHEN %s::integer IS NULL THEN NULL
                            ELSE jsonb_build_object('version', %s::integer)
                        END
                    )
                    """,
                    (
                        str(job_id),
                        str(uuid4()),
                        task,
                        status,
                        result_location,
                        version,
                        version,
                    ),
                )
            finally:
                cursor.execute("ALTER TABLE jobs ENABLE TRIGGER ALL")
    return job_id


def _job_recovery_state(
    database_url: str,
    job_id: UUID,
) -> tuple[str, str | None, str | None, bool]:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status,
                       result_location,
                       to_jsonb(jobs) ->> 'failure_code',
                       finished_at IS NOT NULL
                FROM jobs
                WHERE id = %s::uuid
                """,
                (str(job_id),),
            )
            row = cursor.fetchone()
    assert row is not None
    return row


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


def _drop_variant_check(database_url: str) -> None:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE info_blob_content_references
                DROP CONSTRAINT ck_info_blob_content_references_variant
                """
            )


def _restore_variant_check(database_url: str) -> None:
    with _connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE info_blob_content_references
                ADD CONSTRAINT ck_info_blob_content_references_variant
                CHECK (variant = 'extracted_text')
                """
            )


def test_knowledge_original_reference_migration_guards_and_round_trip(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    command.upgrade(config, _PREVIOUS_REVISION)

    _insert_reference_drift(database_url)
    with pytest.raises(RuntimeError, match="unexpected existing reference"):
        command.upgrade(config, _REVISION)
    _clear_drift(database_url)

    failure_code_lock_job_id = _insert_knowledge_job(
        database_url,
        version=None,
        status="queued",
        result_location="preserve pre-column result",
    )
    writer = _connection(database_url)
    try:
        with writer.cursor() as cursor:
            cursor.execute(
                "UPDATE jobs SET updated_at = updated_at WHERE id = %s::uuid",
                (str(failure_code_lock_job_id),),
            )
        with pytest.raises(RuntimeError, match="failure-code migration could not lock"):
            command.upgrade(config, _FAILURE_CODE_REVISION)
    finally:
        writer.rollback()
        writer.close()
    assert _job_recovery_state(database_url, failure_code_lock_job_id) == (
        "queued",
        "preserve pre-column result",
        None,
        False,
    )
    _clear_drift(database_url)

    command.upgrade(config, _FAILURE_CODE_REVISION)

    durable_job_id = _insert_knowledge_job(
        database_url,
        version=1,
        status="queued",
        result_location="preserve durable result",
    )
    with pytest.raises(RuntimeError, match="active legacy knowledge job"):
        command.upgrade(config, _REVISION)
    assert _job_recovery_state(database_url, durable_job_id) == (
        "queued",
        "preserve durable result",
        None,
        False,
    )
    _clear_drift(database_url)

    active_job_id = _insert_knowledge_job(
        database_url,
        version=None,
        status="in progress",
        result_location="preserve active result",
    )
    with pytest.raises(RuntimeError, match="active legacy knowledge job"):
        command.upgrade(config, _REVISION)
    assert _job_recovery_state(database_url, active_job_id) == (
        "in progress",
        "preserve active result",
        None,
        False,
    )
    _clear_drift(database_url)

    locked_job_id = _insert_knowledge_job(
        database_url,
        version=None,
        status="queued",
        result_location="preserve locked result",
    )
    writer = _connection(database_url)
    try:
        with writer.cursor() as cursor:
            cursor.execute(
                "UPDATE jobs SET updated_at = updated_at WHERE id = %s::uuid",
                (str(locked_job_id),),
            )
        with pytest.raises(RuntimeError, match="could not lock jobs"):
            command.upgrade(config, _REVISION)
    finally:
        writer.rollback()
        writer.close()
    assert _job_recovery_state(database_url, locked_job_id) == (
        "queued",
        "preserve locked result",
        None,
        False,
    )
    _clear_drift(database_url)

    pre_durable_job_ids = (
        _insert_knowledge_job(
            database_url,
            task="upload_info_blob",
            version=None,
            status="queued",
            result_location="clear upload result",
        ),
        _insert_knowledge_job(
            database_url,
            task="transcription",
            version=None,
            status="queued",
            result_location="clear transcription result",
        ),
    )
    _drop_variant_check(database_url)
    with pytest.raises(ProgrammingError, match="does not exist"):
        command.upgrade(config, _REVISION)
    for job_id, result_location in zip(
        pre_durable_job_ids,
        ("clear upload result", "clear transcription result"),
        strict=True,
    ):
        assert _job_recovery_state(database_url, job_id) == (
            "queued",
            result_location,
            None,
            False,
        )

    _restore_variant_check(database_url)
    command.upgrade(config, _REVISION)
    for job_id in pre_durable_job_ids:
        assert _job_recovery_state(database_url, job_id) == (
            "failed",
            None,
            "processing_interrupted",
            True,
        )
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
    command.upgrade(config, "head")
