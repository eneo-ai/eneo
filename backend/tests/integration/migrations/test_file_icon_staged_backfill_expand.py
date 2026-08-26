from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607240310"
_EXPAND_REVISION = "202607231700"


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
        image=_POSTGRES_13_IMAGE,
        username="file_icon_expand",
        password="file_icon_expand_password",
        dbname="file_icon_expand",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        yield database_url, config


def _connect(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _seed_legacy_owners(database_url: str) -> dict[str, str]:
    ids = {
        "tenant": str(uuid4()),
        "user": str(uuid4()),
        "text": str(uuid4()),
        "image": str(uuid4()),
        "derived": str(uuid4()),
        "audio": str(uuid4()),
        "icon": str(uuid4()),
    }
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (ids["tenant"], f"file-icon-expand-{uuid4().hex[:8]}"),
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
                (%s, 'legacy.pdf', 'extracted text', %s, 'legacy-text', 14,
                 'application/pdf', 'text', 'spoken words', %s, %s, NULL),
                (%s, 'legacy.png', NULL, %s, 'legacy-image', 12,
                 'image/png', 'image', NULL, %s, %s, NULL),
                (%s, 'legacy-page.png', NULL, %s, 'legacy-derived', 12,
                 'image/png', 'image', NULL, %s, %s, %s),
                (%s, 'legacy.mp3', NULL, %s, 'legacy-audio', 12,
                 'audio/mpeg', 'audio', NULL, %s, %s, NULL)
            """,
            (
                ids["text"],
                b"original pdf",
                ids["user"],
                ids["tenant"],
                ids["image"],
                b"legacy image",
                ids["user"],
                ids["tenant"],
                ids["derived"],
                b"derived page",
                ids["user"],
                ids["tenant"],
                ids["text"],
                ids["audio"],
                b"legacy audio",
                ids["user"],
                ids["tenant"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO icons (id, blob, mimetype, size, tenant_id)
            VALUES (%s, %s, 'image/png', 11, %s)
            """,
            (ids["icon"], b"legacy icon", ids["tenant"]),
        )
    return ids


def test_expand_inventories_without_copying_or_dropping_bytes(
    migration_database: tuple[str, Config],
) -> None:
    database_url, config = migration_database
    ids = _seed_legacy_owners(database_url)

    command.upgrade(config, _EXPAND_REVISION)

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT owner_kind, owner_id::text, variant, ordinal,
                   tenant_id::text, payload_size_estimate, state
            FROM file_icon_backfill_items
            ORDER BY owner_kind, owner_id, variant, ordinal
            """
        )
        rows = cursor.fetchall()
        actual = {
            (owner_kind, owner_id, variant): (ordinal, tenant_id, estimate, state)
            for owner_kind, owner_id, variant, ordinal, tenant_id, estimate, state in rows
        }
        expected = {
            ("file", ids["text"], "extracted_text"),
            ("file", ids["text"], "original"),
            ("file", ids["text"], "transcription"),
            ("file", ids["image"], "legacy_image"),
            ("file", ids["derived"], "derived_page"),
            ("file", ids["audio"], "original"),
            ("icon", ids["icon"], "primary"),
        }
        assert set(actual) == expected
        assert all(
            ordinal == 0
            and tenant_id == ids["tenant"]
            and estimate > 0
            and state == "pending"
            for ordinal, tenant_id, estimate, state in actual.values()
        )
        assert actual[("file", ids["text"], "extracted_text")][2] == 14
        assert actual[("file", ids["image"], "legacy_image")][2] == 12
        assert actual[("file", ids["derived"], "derived_page")][2] == 12
        assert actual[("file", ids["audio"], "original")][2] == 12
        assert actual[("icon", ids["icon"], "primary")][2] == 11

        cursor.execute("SELECT count(*) FROM object_contents")
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT count(*) FROM file_icon_backfill_campaign")
        assert cursor.fetchone() == (0,)

        cursor.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE (table_name = 'files' AND column_name IN
                   ('text', 'blob', 'checksum', 'size', 'transcription'))
               OR (table_name = 'icons' AND column_name IN
                   ('blob', 'mimetype', 'size'))
            ORDER BY table_name, column_name
            """
        )
        retained_columns = cursor.fetchall()
        assert len(retained_columns) == 8
        assert all(is_nullable == "YES" for _, _, is_nullable in retained_columns)

        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'ck_file_content_references_variant'
            """
        )
        variant_check = cursor.fetchone()
        assert variant_check is not None
        assert "legacy_image" in variant_check[0]
        assert "preview" in variant_check[0]

        cursor.execute(
            """
            SELECT tgname, pg_get_triggerdef(oid)
            FROM pg_trigger
            WHERE tgname LIKE 'freeze_%_legacy_payload_%'
            ORDER BY tgname
            """
        )
        trigger_definitions = dict(cursor.fetchall())
        assert set(trigger_definitions) == {
            "freeze_files_legacy_payload_insert",
            "freeze_files_legacy_payload_update",
            "freeze_icons_legacy_payload_insert",
            "freeze_icons_legacy_payload_update",
        }
        assert (
            "UPDATE OF text, blob, transcription, checksum, size"
            in (trigger_definitions["freeze_files_legacy_payload_update"])
        )
        assert (
            "UPDATE OF blob, mimetype, size"
            in (trigger_definitions["freeze_icons_legacy_payload_update"])
        )


def test_expand_freezes_legacy_payload_writes_but_allows_metadata_and_deletes(
    migration_database: tuple[str, Config],
) -> None:
    database_url, _config = migration_database
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE files SET name = 'renamed.pdf' WHERE name = 'legacy.pdf'"
        )

    with _connect(database_url) as connection, connection.cursor() as cursor:
        with pytest.raises(
            psycopg2.errors.ObjectNotInPrerequisiteState,
            match="legacy payload",
        ):
            cursor.execute(
                "UPDATE files SET transcription = 'changed' WHERE name = 'renamed.pdf'"
            )

    with _connect(database_url) as connection, connection.cursor() as cursor:
        with pytest.raises(
            psycopg2.errors.ObjectNotInPrerequisiteState,
            match="legacy payload",
        ):
            cursor.execute(
                """
                INSERT INTO icons (id, blob, mimetype, size, tenant_id)
                SELECT gen_random_uuid(), 'stale'::bytea, 'image/png', 5, tenant_id
                FROM icons LIMIT 1
                """
            )

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO icons (id, blob, mimetype, size, tenant_id)
            SELECT gen_random_uuid(), NULL, NULL, NULL, tenant_id
            FROM icons LIMIT 1
            """
        )
        cursor.execute("DELETE FROM files WHERE name = 'renamed.pdf'")
        assert cursor.rowcount == 1
