from __future__ import annotations

import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import psycopg2
import pytest
import sqlalchemy as sa
from psycopg2 import sql
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607240310"
_NORMALIZATION_REVISION = "202607231700"
_DEVELOP_PARENT_REVISION = "202607301200"
_FLOW_PARENT_REVISION = "202607291800_attempt_admit_idx"
_MERGE_REVISION = "202607311200"


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


def _file_user_owner_column(cursor) -> str:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'files'
          AND column_name IN ('user_id', 'owner_user_id')
        """
    )
    columns = {row[0] for row in cursor.fetchall()}
    if "owner_user_id" in columns:
        return "owner_user_id"
    if "user_id" in columns:
        return "user_id"
    raise AssertionError("files has no supported user-owner column")


def _seed_legacy_owners(database_url: str) -> dict[str, bytes | str]:
    ids = {
        "tenant": str(uuid4()),
        "user": str(uuid4()),
        "text": str(uuid4()),
        "image": str(uuid4()),
        "generated_image": str(uuid4()),
        "derived": str(uuid4()),
        "audio": str(uuid4()),
        "icon": str(uuid4()),
    }
    payloads: dict[str, bytes] = {
        "text": "Extracted café".encode(),
        "text_original": b"%PDF exact legacy original",
        "image": b"legacy-model-input-image",
        "generated_image": b"legacy-generated-image",
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
            sql.SQL(
                """
            INSERT INTO files (
                id, name, text, blob, checksum, size, mimetype, file_type,
                transcription, {user_owner_column}, tenant_id, parent_file_id
            )
            VALUES
                (%s, 'legacy.pdf', %s, %s, 'legacy-text', %s,
                 'application/pdf', 'text', NULL, %s, %s, NULL),
                (%s, 'legacy.png', NULL, %s, 'legacy-image', %s,
                 'image/png', 'image', NULL, %s, %s, NULL),
                (%s, 'generated.png', NULL, %s, 'legacy-generated', %s,
                 'image/png', 'image', NULL, %s, %s, NULL),
                (%s, 'legacy-page.png', NULL, %s, 'legacy-derived', %s,
                 'image/png', 'image', NULL, %s, %s, %s),
                (%s, 'legacy.mp3', NULL, %s, 'legacy-audio', %s,
                 'audio/mpeg', 'audio', %s, %s, %s, NULL)
            """
            ).format(user_owner_column=sql.Identifier(_file_user_owner_column(cursor))),
            (
                ids["text"],
                payloads["text"].decode(),
                payloads["text_original"],
                len(payloads["text"]),
                ids["user"],
                ids["tenant"],
                ids["image"],
                payloads["image"],
                len(payloads["image"]),
                ids["user"],
                ids["tenant"],
                ids["generated_image"],
                payloads["generated_image"],
                len(payloads["generated_image"]),
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


def _normalization_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "202607231700_normalize_file_icon_content.py"
    )
    spec = spec_from_file_location("file_icon_normalization_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan_nodes(plan: dict[str, object]) -> Generator[dict[str, object], None, None]:
    yield plan
    children = plan.get("Plans")
    if children is None:
        return
    assert isinstance(children, list)
    for child in children:
        assert isinstance(child, dict)
        yield from _plan_nodes(child)


def _assert_byte_bounded_page_plan(
    database_url: str,
    *,
    batch_size: int,
    batch_bytes: int,
) -> None:
    migration = _normalization_module()
    engine = sa.create_engine(database_url)
    try:
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            migration._stage_pending_keys(connection)
            candidate_page = migration._candidate_page(
                migration._file_user_owner_column(connection)
            )
            explained = connection.execute(
                sa.text("EXPLAIN (ANALYZE, FORMAT JSON) " + candidate_page.text),
                {
                    "after_sequence": 0,
                    "batch_size": batch_size,
                    "batch_bytes": batch_bytes,
                },
            ).scalar_one()
    finally:
        engine.dispose()

    root = explained[0]["Plan"]
    window_rows = [
        int(node["Actual Rows"])
        for node in _plan_nodes(root)
        if node.get("Node Type") == "WindowAgg"
    ]
    assert window_rows
    assert max(window_rows) <= batch_size


def test_copy_verify_flip_preserves_legacy_bytes_and_typed_variants(
    migration_database: tuple[str, Config],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = migration_database
    seeded = _seed_legacy_owners(database_url)
    _assert_byte_bounded_page_plan(
        database_url,
        batch_size=2,
        batch_bytes=1,
    )

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
    monkeypatch.setenv("FILE_ICON_NORMALIZATION_BATCH_ROWS", "1")
    monkeypatch.setenv("FILE_ICON_NORMALIZATION_BATCH_BYTES", "1")

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

    # Remove the legacy checksum index before holding a writer open. Otherwise
    # DROP INDEX CONCURRENTLY, rather than the final authority fence, can be the
    # lock waiter observed below.
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS ix_files_checksum")

    racing_file_id = str(uuid4())
    racing_payload = b"racing legacy audio"
    writer = _connect(database_url)
    try:
        with writer.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    """
                INSERT INTO files (
                    id, name, text, blob, checksum, size, mimetype, file_type,
                    transcription, {user_owner_column}, tenant_id, parent_file_id
                )
                VALUES (
                    %s, 'racing.mp3', NULL, %s, 'racing-checksum', %s,
                    'audio/mpeg', 'audio', NULL, %s, %s, NULL
                )
                """
                ).format(
                    user_owner_column=sql.Identifier(_file_user_owner_column(cursor))
                ),
                (
                    racing_file_id,
                    racing_payload,
                    len(racing_payload),
                    seeded["user"],
                    seeded["tenant"],
                ),
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            migration = executor.submit(
                command.upgrade,
                _alembic_config(database_url),
                _NORMALIZATION_REVISION,
            )
            deadline = time.monotonic() + 10
            fence_waiting = False
            while time.monotonic() < deadline:
                with _connect(database_url) as observer, observer.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_locks AS lock
                            JOIN pg_class AS relation
                              ON relation.oid = lock.relation
                            WHERE relation.relname = 'files'
                              AND lock.mode = 'AccessExclusiveLock'
                              AND NOT lock.granted
                        )
                        """
                    )
                    fence_waiting = cursor.fetchone() == (True,)
                if fence_waiting:
                    break
                time.sleep(0.05)

            assert fence_waiting, "migration never established its final write fence"
            writer.commit()
            with pytest.raises(
                RuntimeError,
                match="concurrent File/Icon write",
            ):
                migration.result(timeout=10)
    finally:
        writer.rollback()
        writer.close()

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT blob
            FROM files
            WHERE id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM file_content_references
                  WHERE file_id = files.id
              )
            """,
            (racing_file_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert bytes(row[0]) == racing_payload
        cursor.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE (table_name = 'files' AND column_name = 'blob')
               OR (table_name = 'icons' AND column_name = 'blob')
            """
        )
        assert cursor.fetchone() == (2,)

    command.upgrade(config, _NORMALIZATION_REVISION)

    expected = {
        ("file", seeded["text"], "extracted_text"): seeded["text_payload"],
        ("file", seeded["text"], "original"): seeded["text_original_payload"],
        ("file", seeded["image"], "legacy_image"): seeded["image_payload"],
        (
            "file",
            seeded["generated_image"],
            "legacy_image",
        ): seeded["generated_image_payload"],
        ("file", seeded["derived"], "derived_page"): seeded["derived_payload"],
        ("file", seeded["audio"], "original"): seeded["audio_payload"],
        ("file", racing_file_id, "original"): racing_payload,
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
    with pytest.raises(
        RuntimeError,
        match="restore the pre-flip backup or recover forward",
    ):
        command.downgrade(config, _PREVIOUS_REVISION)


def test_merge_head_upgrades_from_both_parent_histories() -> None:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="develop_flow_merge",
        password="develop_flow_merge_password",
        dbname="develop_flow_merge",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)

        for parent_revision in (
            _DEVELOP_PARENT_REVISION,
            _FLOW_PARENT_REVISION,
        ):
            connection = _connect(database_url)
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute("DROP SCHEMA IF EXISTS public CASCADE")
                    cursor.execute("CREATE SCHEMA public")
                    cursor.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
            finally:
                connection.close()

            command.upgrade(config, parent_revision)
            seeded = (
                _seed_legacy_owners(database_url)
                if parent_revision == _FLOW_PARENT_REVISION
                else None
            )

            command.upgrade(config, _MERGE_REVISION)

            with _connect(database_url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchall() == [(_MERGE_REVISION,)]
                if seeded is not None:
                    cursor.execute(
                        """
                        SELECT DISTINCT created_by_user_id::text
                        FROM object_contents
                        WHERE idempotency_key LIKE 'normalize:file:%'
                        """
                    )
                    assert cursor.fetchall() == [(seeded["user"],)]
