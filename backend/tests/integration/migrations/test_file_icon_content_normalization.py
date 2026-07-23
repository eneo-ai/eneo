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
from eneo.database.tables.files_table import Files
from eneo.database.tables.icons_table import Icons

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607231200"
_NORMALIZATION_REVISION = "202607231700"


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
        username="file_icon_normalization",
        password="file_icon_normalization_password",
        dbname="file_icon_normalization",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        yield database_url, config


def _connect(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _seed_legacy_owners(database_url: str) -> dict[str, bytes | str]:
    ids = {
        "tenant": str(uuid4()),
        "user": str(uuid4()),
        "text": str(uuid4()),
        "image": str(uuid4()),
        "derived": str(uuid4()),
        "audio": str(uuid4()),
        "icon": str(uuid4()),
    }
    payloads: dict[str, bytes] = {
        "text": "Extracted café".encode(),
        "image": b"legacy-model-input-image",
        "derived": b"legacy-derived-page",
        "audio": b"legacy-audio",
        "transcription": "spoken words".encode(),
        "icon": b"legacy-icon",
    }
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (ids["tenant"], f"file-icon-normalization-{uuid4().hex[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO users (
                id, tenant_id, username, email, used_tokens, state
            )
            VALUES (%s, %s, %s, %s, 0, 'active')
            """,
            (
                ids["user"],
                ids["tenant"],
                f"file-icon-{uuid4().hex[:8]}",
                f"file-icon-{uuid4().hex[:12]}@example.test",
            ),
        )
        cursor.execute(
            """
            INSERT INTO files (
                id, name, text, blob, checksum, size, mimetype, file_type,
                transcription, user_id, tenant_id, parent_file_id
            )
            VALUES
                (%s, 'legacy.pdf', %s, NULL, 'legacy-text', %s,
                 'application/pdf', 'text', NULL, %s, %s, NULL),
                (%s, 'legacy.png', NULL, %s, 'legacy-image', %s,
                 'image/png', 'image', NULL, %s, %s, NULL),
                (%s, 'legacy-page.png', NULL, %s, 'legacy-derived', %s,
                 'image/png', 'image', NULL, %s, %s, %s),
                (%s, 'legacy.mp3', NULL, %s, 'legacy-audio', %s,
                 'audio/mpeg', 'audio', %s, %s, %s, NULL)
            """,
            (
                ids["text"],
                payloads["text"].decode(),
                len(payloads["text"]),
                ids["user"],
                ids["tenant"],
                ids["image"],
                payloads["image"],
                len(payloads["image"]),
                ids["user"],
                ids["tenant"],
                ids["derived"],
                payloads["derived"],
                len(payloads["derived"]),
                ids["user"],
                ids["tenant"],
                ids["text"],
                ids["audio"],
                payloads["audio"],
                len(payloads["audio"]),
                payloads["transcription"].decode(),
                ids["user"],
                ids["tenant"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO icons (id, blob, mimetype, size, tenant_id)
            VALUES (%s, %s, 'image/png', %s, %s)
            """,
            (
                ids["icon"],
                payloads["icon"],
                len(payloads["icon"]),
                ids["tenant"],
            ),
        )
    return {**ids, **{f"{name}_payload": value for name, value in payloads.items()}}


def test_copy_verify_flip_preserves_legacy_bytes_and_typed_variants(
    migration_database: tuple[str, Config],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [_NORMALIZATION_REVISION]
    seeded = _seed_legacy_owners(database_url)

    payloads = [
        value
        for key, value in seeded.items()
        if key.endswith("_payload") and isinstance(value, bytes)
    ]
    largest_payload = max(len(payload) for payload in payloads)
    monkeypatch.setenv(
        "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
        str(largest_payload - 1),
    )
    monkeypatch.setenv("OBJECT_CONTENT_RECONCILIATION_BATCH_SIZE", "1")

    with pytest.raises(
        RuntimeError,
        match="above OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
    ):
        command.upgrade(config, _NORMALIZATION_REVISION)

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM object_contents
            WHERE idempotency_key LIKE 'normalize:%'
            """
        )
        assert cursor.fetchone() == (0,)
        cursor.execute(
            """
            CREATE FUNCTION interrupt_file_icon_normalization()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.idempotency_key LIKE 'normalize:%'
                   AND EXISTS (
                       SELECT 1
                       FROM object_contents
                       WHERE idempotency_key LIKE 'normalize:%'
                   )
                THEN
                    RAISE EXCEPTION 'injected migration interruption';
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER interrupt_file_icon_normalization
            BEFORE INSERT ON object_contents
            FOR EACH ROW
            EXECUTE FUNCTION interrupt_file_icon_normalization();
            """
        )

    monkeypatch.setenv(
        "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
        str(largest_payload),
    )
    with pytest.raises(DBAPIError, match="injected migration interruption"):
        command.upgrade(config, _NORMALIZATION_REVISION)

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM object_contents
            WHERE idempotency_key LIKE 'normalize:%'
            """
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            """
            DROP TRIGGER interrupt_file_icon_normalization ON object_contents;
            DROP FUNCTION interrupt_file_icon_normalization();
            """
        )

    command.upgrade(config, _NORMALIZATION_REVISION)

    expected = {
        ("file", seeded["text"], "extracted_text"): seeded["text_payload"],
        ("file", seeded["image"], "model_input"): seeded["image_payload"],
        ("file", seeded["derived"], "derived_page"): seeded["derived_payload"],
        ("file", seeded["audio"], "original"): seeded["audio_payload"],
        (
            "file",
            seeded["audio"],
            "transcription",
        ): seeded["transcription_payload"],
        ("icon", seeded["icon"], "primary"): seeded["icon_payload"],
    }
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 'file', reference.file_id::text, reference.variant,
                   payload.payload, content.sha256, content.size_bytes,
                   content.storage_kind, content.state, content.reference_count,
                   content.idempotency_key
            FROM file_content_references AS reference
            JOIN object_contents AS content ON content.id = reference.content_id
            JOIN inline_content_payloads AS payload
              ON payload.content_id = content.id
            UNION ALL
            SELECT 'icon', reference.icon_id::text, reference.variant,
                   payload.payload, content.sha256, content.size_bytes,
                   content.storage_kind, content.state, content.reference_count,
                   content.idempotency_key
            FROM icon_content_references AS reference
            JOIN object_contents AS content ON content.id = reference.content_id
            JOIN inline_content_payloads AS payload
              ON payload.content_id = content.id
            """
        )
        rows = cursor.fetchall()
        assert len(rows) == len(expected)
        for (
            owner_kind,
            owner_id,
            variant,
            payload,
            digest,
            size_bytes,
            storage_kind,
            state,
            reference_count,
            idempotency_key,
        ) in rows:
            expected_payload = expected[(owner_kind, owner_id, variant)]
            assert bytes(payload) == expected_payload
            assert bytes(digest) == sha256(expected_payload).digest()
            assert size_bytes == len(expected_payload)
            assert storage_kind == "postgres_inline"
            assert state == "available"
            assert reference_count == 1
            assert idempotency_key.startswith("normalize:")

        cursor.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE (table_name = 'files'
                   AND column_name IN (
                       'text', 'blob', 'checksum', 'size', 'transcription'
                   ))
               OR (table_name = 'icons'
                   AND column_name IN ('blob', 'mimetype', 'size'))
            """
        )
        assert cursor.fetchall() == []
        cursor.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('files', 'icons')
            """
        )
        columns: dict[str, set[str]] = {"files": set(), "icons": set()}
        for table_name, column_name in cursor.fetchall():
            columns[table_name].add(column_name)
        assert columns["files"] == set(Files.__table__.columns.keys())
        assert columns["icons"] == set(Icons.__table__.columns.keys())

    with pytest.raises(
        RuntimeError,
        match="restore the pre-flip backup or recover forward",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)
