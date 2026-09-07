import asyncio
import json
import os
import subprocess
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest
import sqlalchemy as sa
from psycopg2 import sql
from testcontainers.postgres import PostgresContainer

from alembic import command
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.file_icon_preflight import run_file_icon_preflight
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models
_connect = expand._connect
_seed_legacy_owners = expand._seed_legacy_owners

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


@pytest.fixture
def migration_database(request):
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="file_icon_expand",
        password="file_icon_expand_password",
        dbname="file_icon_expand",
    ) as postgres:
        database_url = postgres.get_connection_url()
        config = expand._alembic_config(database_url)
        command.upgrade(config, getattr(request, "param", expand._PREVIOUS_REVISION))
        yield database_url, config


def test_preflight_matches_frozen_inventory_without_changing_legacy_database(
    migration_database,
):
    database_url, config = migration_database
    ids = _seed_legacy_owners(database_url)
    with _connect(database_url) as connection, connection.cursor() as cursor:
        # Empty bytes are work; an absent payload and a deleted owner are not.
        cursor.execute(
            "UPDATE files SET text = '', transcription = NULL WHERE id = %s",
            (ids["text"],),
        )
        cursor.execute(
            "UPDATE files SET transcription = 'åäö' WHERE id = %s",
            (ids["image"],),
        )
        cursor.execute("DELETE FROM files WHERE id = %s", (ids["audio"],))
        cursor.execute("SELECT version_num FROM alembic_version")
        (revision,) = cursor.fetchone()

    result = asyncio.run(run_file_icon_preflight(database_url))
    assert result.outcome == "ready"
    assert result.schema_state == "pre_expand"
    assert result.alembic_revision == revision == "202607240310"
    assert result.server_encoding == "UTF8"
    assert result.capacity.campaign_admitted_logical_bytes is None
    assert result.capacity.host_free_bytes is None
    assert result.capacity.estimated_extra_database_bytes is None
    assert result.capacity.generated_wal_bytes is None
    assert result.capacity.retained_wal_bytes is None

    facts = {
        (row.owner_kind, row.variant): (row.remaining_count, row.remaining_bytes)
        for row in result.variants
    }
    assert facts == {
        ("file", "extracted_text"): (1, 0),
        ("file", "original"): (1, len(b"original pdf")),
        ("file", "transcription"): (1, len("åäö".encode())),
        ("file", "legacy_image"): (1, len(b"legacy image")),
        ("file", "derived_page"): (1, len(b"derived page")),
        ("icon", "primary"): (1, len(b"legacy icon")),
    }
    assert sum(row.size_bands.empty for row in result.variants) == 1
    assert result.capacity.remaining_logical_bytes == sum(n for _, n in facts.values())

    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone() == (revision,)
        cursor.execute("SELECT to_regclass('file_icon_backfill_items')")
        assert cursor.fetchone() == (None,)
        cursor.execute("SELECT text, blob FROM files WHERE id = %s", (ids["text"],))
        text, blob = cursor.fetchone()
        assert text == "" and bytes(blob) == b"original pdf"

    command.upgrade(config, "202607231745")
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT owner_kind, variant, count(*), sum(payload_size_estimate) "
            "FROM file_icon_backfill_items GROUP BY owner_kind, variant"
        )
        assert {
            (kind, variant): (n, int(size)) for kind, variant, n, size in cursor
        } == facts
    expanded = asyncio.run(run_file_icon_preflight(database_url))
    assert expanded.outcome == "ready"
    assert expanded.schema_state == "expanded"
    assert [asdict(row) for row in expanded.variants] == [
        asdict(row) for row in result.variants
    ]

    command.upgrade(config, "head")
    with _connect(database_url) as connection, connection.cursor() as cursor:
        for owner, variant, payload, state in (
            (ids["text"], "original", b"original pdf", "available"),
            (ids["derived"], "derived_page", b"derived page", "failed"),
        ):
            content_id = str(uuid4())
            digest = sha256(payload).digest()
            cursor.execute(
                """
                INSERT INTO object_contents (
                    id, tenant_id, storage_kind, state, access_class, sha256,
                    size_bytes, verified_media_type, idempotency_key,
                    request_fingerprint, available_at, failure_code
                ) VALUES (%s, %s, 'postgres_inline', %s, 'private_resource',
                          %s, %s, 'application/octet-stream', %s, %s, now(), NULL)
                """,
                (
                    content_id,
                    ids["tenant"],
                    "available",
                    digest,
                    len(payload),
                    content_id,
                    digest,
                ),
            )
            cursor.execute(
                "INSERT INTO inline_content_payloads (content_id, payload) VALUES (%s, %s)",
                (content_id, payload),
            )
            cursor.execute(
                "INSERT INTO file_content_references (file_id, content_id, variant, ordinal) VALUES (%s, %s, %s, 0)",
                (owner, content_id, variant),
            )
            if state == "failed":
                cursor.execute(
                    "UPDATE object_contents SET state = 'failed', failure_code = 'backend_missing' WHERE id = %s",
                    (content_id,),
                )
        cursor.execute(
            "INSERT INTO file_icon_backfill_campaign (id, target_kind, state, capacity_admitted_bytes) VALUES (%s, 'postgres_inline', 'active', 1000)",
            (str(uuid4()),),
        )
    partial = asyncio.run(
        run_file_icon_preflight(
            database_url,
            core_settings=ObjectContentCoreSettings(
                inline_maximum_bytes=11, inline_io_chunk_bytes=1
            ),
        )
    )
    assert partial.outcome == "blocked"
    assert [issue.code for issue in partial.blockers] == ["oversized_legacy_items"]
    partial_facts = {(row.owner_kind, row.variant): row for row in partial.variants}
    original = partial_facts["file", "original"]
    assert original.available_reference_count == 1
    assert original.available_reference_bytes == len(b"original pdf")
    assert original.remaining_count == original.oversized_count == 0
    assert partial_facts["file", "derived_page"].oversized_count == 1
    assert partial_facts["file", "derived_page"].available_reference_count == 0
    assert partial_facts["icon", "primary"].oversized_count == 0  # Exact limit.
    assert partial.capacity.campaign_admitted_logical_bytes == 1000
    assert (
        partial.capacity.remaining_logical_bytes
        == result.capacity.remaining_logical_bytes - len(b"original pdf")
    )
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE object_content_deployment_policy SET new_write_storage_target = 'object_store' WHERE id = 1"
        )
    remote = asyncio.run(run_file_icon_preflight(database_url))
    assert "unsupported_legacy_target" in [issue.code for issue in remote.blockers]
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE icons DISABLE TRIGGER freeze_icons_legacy_payload_update"
        )
    unfenced = asyncio.run(run_file_icon_preflight(database_url))
    assert unfenced.schema_state == "unsupported"
    assert "unsupported_schema" in [issue.code for issue in unfenced.blockers]


@pytest.mark.parametrize("migration_database", ["202607071200"], indirect=True)
def test_preflight_supports_legacy_release_before_reference_tables(migration_database):
    database_url, _ = migration_database
    _seed_legacy_owners(database_url)
    result = asyncio.run(run_file_icon_preflight(database_url))
    assert result.outcome == "ready"
    assert result.schema_state == "pre_expand"
    assert sum(row.remaining_count for row in result.variants) == 7
    assert all(row.available_reference_count == 0 for row in result.variants)


def test_preflight_refuses_non_utf8_before_source_scan(migration_database):
    database_url, _ = migration_database
    name = f"preflight_latin1_{uuid4().hex}"
    connection = _connect(database_url)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE DATABASE {} ENCODING 'LATIN1' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
                ).format(sql.Identifier(name))
            )
        latin1_url = (
            sa.engine.make_url(database_url)
            .set(database=name)
            .render_as_string(hide_password=False)
        )
        result = asyncio.run(run_file_icon_preflight(latin1_url))
        assert result.outcome == "blocked"
        assert result.server_encoding == "LATIN1"
        assert "unsupported_encoding" in [issue.code for issue in result.blockers]
        assert result.variants == []
    finally:
        connection.close()


@pytest.mark.parametrize(
    "change,undo,code",
    [
        (
            "ALTER TABLE files RENAME COLUMN blob TO old_blob",
            "ALTER TABLE files RENAME COLUMN old_blob TO blob",
            "unsupported_schema",
        ),
        (
            "UPDATE alembic_version SET version_num = 'unknown-preflight-revision'",
            None,
            "unsupported_revision",
        ),
    ],
)
def test_preflight_refuses_unknown_schema_or_revision(
    migration_database, change, undo, code
):
    database_url, _ = migration_database
    with _connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        (revision,) = cursor.fetchone()
        cursor.execute(change)
    try:
        result = asyncio.run(run_file_icon_preflight(database_url))
        assert result.outcome == "blocked"
        assert result.schema_state == "unsupported"
        assert result.variants == []
        assert result.capacity.remaining_logical_bytes is None
        assert code in [issue.code for issue in result.blockers]
    finally:
        with _connect(database_url) as connection, connection.cursor() as cursor:
            if undo:
                cursor.execute(undo)
            else:
                cursor.execute(
                    "UPDATE alembic_version SET version_num = %s", (revision,)
                )


def test_preflight_timeout_is_incomplete_and_leaves_no_waiter(migration_database):
    database_url, _ = migration_database
    with _connect(database_url) as blocker, blocker.cursor() as cursor:
        cursor.execute("LOCK TABLE files IN ACCESS EXCLUSIVE MODE")
        started = monotonic()
        result = asyncio.run(run_file_icon_preflight(database_url, timeout_seconds=1))
        assert monotonic() - started < 5
        assert result.outcome == "incomplete"
        assert result.variants == []
        assert result.capacity.remaining_logical_bytes is None
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'"
        )
        assert cursor.fetchone() == (0,)


def test_preflight_cli_json_exit_codes_and_credentials(
    migration_database, test_settings
):
    database_url, _ = migration_database
    _seed_legacy_owners(database_url)
    with _connect(database_url) as connection:
        parameters = connection.get_dsn_parameters()
    environment = os.environ.copy()
    environment.update(
        {
            name.upper(): str(getattr(test_settings, name))
            for name, model_field in type(test_settings).model_fields.items()
            if model_field.is_required()
        }
    )
    environment.update(
        POSTGRES_HOST=parameters["host"],
        POSTGRES_PORT=parameters["port"],
        POSTGRES_USER=parameters["user"],
        POSTGRES_PASSWORD="file_icon_expand_password",
        POSTGRES_DB=parameters["dbname"],
        LOGLEVEL="DEBUG",
        TESTING="true",
    )

    def run():
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eneo.object_content.file_icon_migration",
                "preflight",
                "--timeout-seconds",
                "5",
            ],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert "file_icon_expand_password" not in result.stdout + result.stderr
        assert "original pdf" not in result.stdout + result.stderr
        assert len(result.stdout) < 20_000
        return result.returncode, json.loads(result.stdout)

    exit_code, output = run()
    assert exit_code == 0
    assert output["format_version"] == 1
    assert output["outcome"] == "ready"
    environment["OBJECT_CONTENT_INLINE_MAXIMUM_BYTES"] = "1"
    environment["OBJECT_CONTENT_INLINE_IO_CHUNK_BYTES"] = "1"
    exit_code, output = run()
    assert exit_code == 2
    assert output["outcome"] == "blocked"
    environment["POSTGRES_PASSWORD"] = "deliberately-wrong-preflight-password"
    exit_code, output = run()
    assert exit_code == 3
    assert output["outcome"] == "incomplete"
