"""Start the contraction app against an actual bridge backup and its next backup.

Run with ``uv run python scripts/test_file_icon_release_chain.py`` or separately
with ``pytest -m migration_isolation`` and ``ENEO_FILE_ICON_CONTRACTION_BACKUP``
pointing to the bridge rehearsal's exported dump.
Both restores run exclusively in this test's disposable PostgreSQL container.
"""

import json
import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from eneo.database.database import sessionmanager
from eneo.main.config import set_settings
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand
from tests.integration.migrations.test_file_icon_legacy_contraction import (
    _connect,
    _inline_reference_facts,
    _legacy_columns,
)
from tests.integration.object_content.test_file_original_download import (
    _signed_download,
)

cleanup_database = expand.cleanup_database
seed_default_models = expand.seed_default_models
encryption_service = expand.encryption_service

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    if not os.getenv("ENEO_FILE_ICON_CONTRACTION_BACKUP"):
        pytest.fail(
            "Run uv run python scripts/test_file_icon_release_chain.py to prepare the bridge backup"
        )
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="integration_test_user",
        password="integration_test_password",
        dbname="integration_test_db",
    ).with_kwargs(mem_limit="2g", nano_cpus=2_000_000_000) as postgres:
        yield postgres


def _restore(postgres, path, database_name):
    with path.open("rb") as source:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                postgres.get_wrapped_container().id,
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "-U",
                "integration_test_user",
                "-d",
                database_name,
            ],
            stdin=source,
            capture_output=True,
            check=True,
        )


def _read_samples(url):
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT f.id::text, r.variant, p.payload FROM files f "
            "JOIN file_content_references r ON r.file_id=f.id "
            "JOIN object_contents c ON c.id=r.content_id "
            "JOIN inline_content_payloads p ON p.content_id=c.id "
            "WHERE (f.name IN ('legacy-0', 'legacy-1', 'legacy-2') OR f.file_type='audio') "
            "ORDER BY f.name, r.variant"
        )
        files = [
            (file_id, variant, bytes(payload)) for file_id, variant, payload in cursor
        ]
        cursor.execute(
            "SELECT r.icon_id::text, p.payload FROM icon_content_references r "
            "JOIN inline_content_payloads p ON p.content_id=r.content_id"
        )
        icons = [(icon_id, bytes(payload)) for icon_id, payload in cursor]
    assert files and icons
    return files, icons


@pytest.fixture(scope="session")
async def setup_database(test_settings, postgres_container):
    backup = Path(os.environ["ENEO_FILE_ICON_CONTRACTION_BACKUP"])
    started = time.perf_counter()
    _restore(postgres_container, backup, test_settings.postgres_db)
    url = test_settings.sync_database_url
    before = _inline_reference_facts(url)
    assert before and all(row[-2] == row[-1] for row in before)
    files, icons = _read_samples(url)
    migration_started = time.perf_counter()
    command.upgrade(expand._alembic_config(url), "head")
    migration_seconds = time.perf_counter() - migration_started
    assert _legacy_columns(url) == set()
    assert _inline_reference_facts(url) == before
    sessionmanager.init(test_settings.database_url)
    try:
        yield {
            "facts": before,
            "files": files,
            "icons": icons,
            "started": started,
            "report": {
                "bridge_revision": "202609071000",
                "contraction_revision": "202609081400",
                "postgres_image": expand._POSTGRES_13_IMAGE,
                "source_backup_bytes": backup.stat().st_size,
                "verified_references": len(before),
                "verified_payload_bytes": sum(row[7] for row in before),
                "contraction_seconds": migration_seconds,
                "object_store": "not configured; PostgreSQL-only profile",
            },
        }
    finally:
        await sessionmanager.close()


async def _assert_reads(client, headers, state, uploads):
    for file_id, variant, payload in state["files"]:
        if variant == "transcription":
            response = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["transcription"] == payload.decode()
            continue
        response = await _signed_download(
            client, headers, UUID(file_id), original=variant == "original"
        )
        assert response.status_code == 200, response.text
        assert response.content == payload
    for icon_id, payload in state["icons"]:
        response = await client.get(f"/api/v1/icons/{icon_id}/")
        assert response.status_code == 200 and response.content == payload
    for file_id, payload in uploads:
        response = await _signed_download(client, headers, UUID(file_id), original=True)
        assert response.status_code == 200 and response.content == payload


async def test_bridge_backup_contracts_and_serves_after_a_second_restore(
    setup_database,
    postgres_container,
    test_settings,
    client,
    db_container,
    admin_user_api_key,
):
    from eneo.object_content.runtime import object_content_runtime
    from eneo.server.dependencies.lifespan import startup

    state = setup_database
    report = state["report"]
    headers = {"X-API-Key": admin_user_api_key.key}
    uploads = []
    async with db_container():
        await _assert_reads(client, headers, state, uploads)
        for index in range(3):
            payload = f"after contraction {index} åäö\n".encode() * 64
            response = await client.post(
                "/api/v1/files/",
                headers=headers,
                files={"upload_file": ("after.txt", payload, "text/plain")},
            )
            assert response.status_code == 200, response.text
            uploads.append((response.json()["id"], payload))
        await _assert_reads(client, headers, state, uploads)
    before_restore = _inline_reference_facts(test_settings.sync_database_url)
    container_id = postgres_container.get_wrapped_container().id
    with TemporaryDirectory(prefix="eneo-contraction-restore-") as temporary:
        backup = Path(temporary) / "contracted.dump"
        with backup.open("wb") as output:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "pg_dump",
                    "-U",
                    "integration_test_user",
                    "-Fc",
                    "-d",
                    test_settings.postgres_db,
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                check=True,
            )
        report["contracted_backup_bytes"] = backup.stat().st_size
        subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "createdb",
                "-U",
                "integration_test_user",
                "contracted_restore",
            ],
            capture_output=True,
            check=True,
        )
        restore_started = time.perf_counter()
        _restore(postgres_container, backup, "contracted_restore")
        report["contracted_restore_seconds"] = time.perf_counter() - restore_started
    restored_url = (
        test_settings.sync_database_url.rsplit("/", 1)[0] + "/contracted_restore"
    )
    assert _inline_reference_facts(restored_url) == before_restore
    assert _legacy_columns(restored_url) == set()
    await object_content_runtime.stop()
    await sessionmanager.close()
    set_settings(test_settings.model_copy(update={"postgres_db": "contracted_restore"}))
    startup_started = time.perf_counter()
    await startup()
    report["restored_startup_seconds"] = time.perf_counter() - startup_started
    async with db_container():
        await _assert_reads(client, headers, state, uploads)
    report["new_uploads_verified"] = len(uploads)
    report["failed_api_requests"] = 0
    report["byte_or_reference_mismatches"] = 0
    report["elapsed_seconds"] = time.perf_counter() - state["started"]
    if output := os.getenv("ENEO_FILE_ICON_CONTRACTION_OUTPUT"):
        Path(output).write_text(json.dumps(report, indent=2) + "\n")
