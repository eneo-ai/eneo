from __future__ import annotations

from collections.abc import Generator
from hashlib import sha256
from pathlib import Path
from unittest.mock import ANY
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
_PREVIOUS_REVISION = "202607221700"
_SPLIT_REVISION = "202607231200"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    """Keep this migration packet independent of the shared PG16 fixture."""
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
        image=_POSTGRES_13_IMAGE,
        username="object_content_backend_split",
        password="object_content_backend_split_password",
        dbname="object_content_backend_split",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        yield database_url, config


def _connect(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _insert_legacy_content(database_url: str) -> tuple[str, str, str]:
    tenant_id = str(uuid4())
    content_id = str(uuid4())
    tombstoned_content_id = str(uuid4())
    digest = sha256(b"legacy remote content").digest()
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (tenant_id, f"object-content-split-{uuid4().hex[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO object_contents (
                id, tenant_id, object_key, state, access_class, sha256,
                size_bytes, declared_media_type, verified_media_type,
                idempotency_key, request_fingerprint, failure_code,
                remote_observed_at
            )
            VALUES (
                %s, %s, %s, 'failed', 'private_resource', %s,
                21, 'text/plain', 'text/plain', %s, %s,
                'remote_missing', now()
            )
            """,
            (
                content_id,
                tenant_id,
                "v1/legacy-object",
                digest,
                "legacy-object",
                digest,
            ),
        )
        cursor.execute(
            """
            INSERT INTO object_contents (
                id, tenant_id, object_key, state, access_class, sha256,
                size_bytes, declared_media_type, verified_media_type,
                idempotency_key, request_fingerprint, delete_requested_at,
                remote_deleted_at
            )
            VALUES (
                %s, %s, %s, 'tombstoned', 'private_resource', %s,
                21, 'text/plain', 'text/plain', %s, %s, now(), now()
            )
            """,
            (
                tombstoned_content_id,
                tenant_id,
                "v1/legacy-tombstone",
                digest,
                "legacy-tombstone",
                digest,
            ),
        )
    return tenant_id, content_id, tombstoned_content_id


def _insert_inline_content(database_url: str, tenant_id: str) -> str:
    user_id = str(uuid4())
    file_id = str(uuid4())
    content_id = str(uuid4())
    payload = b"inline downgrade fence"
    digest = sha256(payload).digest()
    with _connect(database_url) as connection, connection.cursor() as cursor:
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
                f"object-content-{uuid4().hex[:8]}",
                f"object-content-{uuid4().hex[:12]}@example.test",
            ),
        )
        cursor.execute(
            """
            INSERT INTO files (
                id, name, text, blob, checksum, size, mimetype, file_type,
                transcription, user_id, tenant_id
            )
            VALUES (
                %s, 'inline.txt', NULL, NULL, %s, %s, 'text/plain', 'text',
                NULL, %s, %s
            )
            """,
            (file_id, digest.hex(), len(payload), user_id, tenant_id),
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
                %s, %s, %s, 'postgres_inline', 'available',
                'private_resource', %s, %s, 'text/plain', 'text/plain',
                %s, %s, now()
            )
            """,
            (
                content_id,
                tenant_id,
                user_id,
                digest,
                len(payload),
                f"inline-{content_id}",
                digest,
            ),
        )
        cursor.execute(
            """
            INSERT INTO inline_content_payloads (content_id, payload)
            VALUES (%s, %s)
            """,
            (content_id, payload),
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
    return content_id


def test_populated_object_store_round_trip_and_inline_downgrade_fence(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [_SPLIT_REVISION]
    tenant_id, content_id, tombstoned_content_id = _insert_legacy_content(database_url)

    command.upgrade(config, _SPLIT_REVISION)
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT content.storage_kind, content.failure_code,
                   descriptor.object_key, descriptor.remote_observed_at
            FROM object_contents content
            JOIN object_store_objects descriptor
              ON descriptor.content_id = content.id
            WHERE content.id = %s
            """,
            (content_id,),
        )
        assert cursor.fetchone() == (
            "object_store",
            "backend_missing",
            "v1/legacy-object",
            ANY,
        )
        cursor.execute(
            """
            SELECT state, payload_deleted_at IS NOT NULL,
                   descriptor.object_key
            FROM object_contents content
            JOIN object_store_objects descriptor
              ON descriptor.content_id = content.id
            WHERE content.id = %s
            """,
            (tombstoned_content_id,),
        )
        assert cursor.fetchone() == (
            "tombstoned",
            True,
            "v1/legacy-tombstone",
        )

    command.downgrade(config, _PREVIOUS_REVISION)
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT object_key, failure_code, remote_observed_at
            FROM object_contents
            WHERE id = %s
            """,
            (content_id,),
        )
        assert cursor.fetchone() == (
            "v1/legacy-object",
            "remote_missing",
            ANY,
        )
        cursor.execute(
            """
            SELECT state, remote_deleted_at IS NOT NULL, object_key
            FROM object_contents
            WHERE id = %s
            """,
            (tombstoned_content_id,),
        )
        assert cursor.fetchone() == (
            "tombstoned",
            True,
            "v1/legacy-tombstone",
        )

    command.upgrade(config, _SPLIT_REVISION)
    _insert_inline_content(database_url, tenant_id)
    with pytest.raises(
        DBAPIError,
        match="cannot downgrade object-content schema while inline content exists",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)
