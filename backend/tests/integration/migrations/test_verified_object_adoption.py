from __future__ import annotations

from collections.abc import Generator
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607251700"
_VERIFIED_ADOPTION_REVISION = "202607261000"


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


def _current_revision(database_url: str) -> str | None:
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            row = cursor.fetchone()
            return None if row is None else str(row[0])
    finally:
        connection.close()


def _insert_object_store_descriptor(
    database_url: str,
    *,
    payload: bytes,
) -> str:
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    file_id = str(uuid4())
    content_id = str(uuid4())
    digest = sha256(payload).digest()
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tenants (id, name, quota_limit, state)
                VALUES (%s, %s, 1000000, 'active')
                """,
                (tenant_id, f"verification-chunks-{uuid4().hex[:8]}"),
            )
            cursor.execute(
                """
                INSERT INTO users (
                    id, tenant_id, username, email, used_tokens, state
                )
                VALUES (%s, %s, %s, %s, 0, 'active')
                """,
                (
                    user_id,
                    tenant_id,
                    f"verification-{uuid4().hex[:8]}",
                    f"verification-{uuid4().hex[:12]}@example.test",
                ),
            )
            cursor.execute(
                """
                INSERT INTO files (
                    id, name, mimetype, file_type, user_id, tenant_id,
                    parent_file_id
                )
                VALUES (
                    %s, %s, 'application/octet-stream', 'audio', %s, %s, NULL
                )
                """,
                (
                    file_id,
                    f"{file_id}.bin",
                    user_id,
                    tenant_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO object_contents (
                    id, tenant_id, created_by_user_id, storage_kind, state,
                    access_class, sha256, size_bytes, declared_media_type,
                    verified_media_type, idempotency_key, request_fingerprint,
                    available_at
                )
                VALUES (
                    %s, %s, %s, 'object_store', 'available',
                    'private_resource', %s, %s, 'application/octet-stream',
                    'application/octet-stream', %s, %s, now()
                )
                """,
                (
                    content_id,
                    tenant_id,
                    user_id,
                    digest,
                    len(payload),
                    f"verification-{content_id}",
                    digest,
                ),
            )
            cursor.execute(
                """
                INSERT INTO object_store_objects (
                    content_id, storage_kind, object_key
                )
                VALUES (%s, 'object_store', %s)
                """,
                (content_id, f"v1/verification/{content_id}"),
            )
            cursor.execute(
                """
                INSERT INTO file_content_references (
                    file_id, content_id, variant, ordinal
                )
                VALUES (%s, %s, 'original', 0)
                """,
                (file_id, content_id),
            )
        connection.commit()
    finally:
        connection.close()
    return content_id


def _assert_backfilled_descriptor(
    database_url: str,
    *,
    content_id: str,
    payload: bytes,
) -> None:
    connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT verification_chunk_size_bytes,
                       verification_chunk_sha256
                FROM object_store_objects
                WHERE content_id = %s
                """,
                (content_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == max(1, len(payload))
            assert bytes(row[1]) == sha256(payload).digest()
    finally:
        connection.close()


def test_verified_adoption_and_chunk_manifest_round_trip_has_one_head() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="verified_adoption_migration",
        password="verified_adoption_migration_password",
        dbname="verified_adoption_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert len(heads) == 1
        head = heads[0]

        command.upgrade(config, _PREVIOUS_REVISION)
        assert _current_revision(database_url) == _PREVIOUS_REVISION

        command.upgrade(config, _VERIFIED_ADOPTION_REVISION)
        nonempty_payload = b"legacy ranged object"
        nonempty_id = _insert_object_store_descriptor(
            database_url,
            payload=nonempty_payload,
        )
        empty_id = _insert_object_store_descriptor(database_url, payload=b"")

        command.upgrade(config, "head")
        assert _current_revision(database_url) == head
        _assert_backfilled_descriptor(
            database_url,
            content_id=nonempty_id,
            payload=nonempty_payload,
        )
        _assert_backfilled_descriptor(
            database_url,
            content_id=empty_id,
            payload=b"",
        )

        command.downgrade(config, _VERIFIED_ADOPTION_REVISION)
        assert _current_revision(database_url) == _VERIFIED_ADOPTION_REVISION

        command.upgrade(config, "head")
        assert _current_revision(database_url) == head
        _assert_backfilled_descriptor(
            database_url,
            content_id=nonempty_id,
            payload=nonempty_payload,
        )
        _assert_backfilled_descriptor(
            database_url,
            content_id=empty_id,
            payload=b"",
        )

        command.downgrade(config, _VERIFIED_ADOPTION_REVISION)
        assert _current_revision(database_url) == _VERIFIED_ADOPTION_REVISION
        connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    ALTER TABLE object_store_objects
                    RENAME TO object_store_objects_seed;
                    CREATE VIEW object_store_objects AS
                    SELECT descriptor.*
                    FROM object_store_objects_seed AS descriptor
                    CROSS JOIN generate_series(1, 5001)
                    """
                )
            connection.commit()
        finally:
            connection.close()

        with pytest.raises(
            DBAPIError,
            match="object verification backfill found 10002 descriptors",
        ):
            command.upgrade(config, "head")

        assert _current_revision(database_url) == _VERIFIED_ADOPTION_REVISION
        connection = psycopg2.connect(database_url.replace("+psycopg2", ""))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_name = 'object_store_objects'
                      AND column_name IN (
                          'verification_chunk_size_bytes',
                          'verification_chunk_sha256'
                      )
                    """
                )
                assert cursor.fetchone() == (0,)
        finally:
            connection.close()
