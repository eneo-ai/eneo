"""Authenticated ASGI requests during adoption; not a production load benchmark."""

import asyncio
import json
from time import perf_counter
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.file_icon_backfill_table import FileIconBackfillItems
from eneo.object_content.file_icon_backfill import FileIconBackfillState
from tests.integration.object_content.test_file_icon_inline_backfill import (
    _backfill,
    _seed_legacy_text,
)
from tests.integration.object_content.test_file_original_download import (
    _signed_download,
)

pytestmark = pytest.mark.integration


async def test_authenticated_uploads_and_downloads_continue_during_legacy_adoption(
    client, db_container, admin_user, admin_user_api_key, capsys
):
    # Keep the production runtime alive across overlapping requests and batches.
    async with db_container():
        async with sessionmanager.session() as session, session.begin():
            server_version = await session.scalar(sa.text("SHOW server_version"))
        legacy_payload = b"legacy text\n" * 4096
        legacy_files = [
            await _seed_legacy_text(
                sessionmanager, payload=legacy_payload, user_email=admin_user.email
            )
            for _ in range(20)
        ]
        worker = _backfill(
            sessionmanager,
            batch_rows=2,
            batch_bytes=1024 * 1024,
            inline_maximum_bytes=1024 * 1024,
            inline_capacity_ack=20 * len(legacy_payload),
        )
        headers = {"X-API-Key": admin_user_api_key.key}
        request_seconds = []
        uploads = []

        async def foreground(round_number):
            started = perf_counter()
            legacy = await _signed_download(
                client,
                headers,
                legacy_files[round_number % len(legacy_files)],
                original=False,
            )
            assert legacy.status_code == 200, legacy.text
            assert legacy.content == legacy_payload
            payload = f"new upload {round_number}\n".encode() * 1024
            upload = await client.post(
                "/api/v1/files/",
                files={
                    "upload_file": (f"new-{round_number}.txt", payload, "text/plain")
                },
                headers=headers,
            )
            assert upload.status_code == 200, upload.text
            file_id = UUID(upload.json()["id"])
            original = await _signed_download(client, headers, file_id, original=True)
            assert original.status_code == 200, original.text
            assert original.content == payload
            uploads.append((file_id, payload))
            request_seconds.append(perf_counter() - started)

        started = perf_counter()
        active_copy_rounds = 0
        async with asyncio.timeout(60):
            for round_number in range(30):
                result, _ = await asyncio.gather(
                    worker.run_once(), foreground(round_number)
                )
                active_copy_rounds += int(result.completed_count > 0)
                if result.state is FileIconBackfillState.COMPLETE:
                    break
            else:
                pytest.fail(
                    "Migration did not finish within its bounded fixture workload"
                )
        elapsed_seconds = perf_counter() - started
        assert active_copy_rounds == 10
        for file_id in legacy_files:
            response = await _signed_download(client, headers, file_id, original=False)
            assert response.status_code == 200, response.text
            assert response.content == legacy_payload
        for file_id, payload in uploads:
            response = await _signed_download(client, headers, file_id, original=True)
            assert response.status_code == 200, response.text
            assert response.content == payload
        async with sessionmanager.session() as session, session.begin():
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(FileIconBackfillItems)
                    .where(FileIconBackfillItems.state == "done")
                )
                == 20
            )
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(FileIconBackfillItems)
                    .where(
                        FileIconBackfillItems.owner_id.in_(
                            [file_id for file_id, _ in uploads]
                        )
                    )
                )
                == 0
            )

    with capsys.disabled():
        print(
            "FILE_ICON_MIGRATION_TRAFFIC_RESULT "
            + json.dumps(
                {
                    "transport": "in-process ASGI; real authenticated production routes",
                    "postgres_version": server_version,
                    "legacy_items": len(legacy_files),
                    "legacy_bytes": len(legacy_files) * len(legacy_payload),
                    "foreground_rounds": len(request_seconds),
                    "active_copy_rounds": active_copy_rounds,
                    "elapsed_seconds": elapsed_seconds,
                    "max_foreground_round_seconds": max(request_seconds),
                    "failed_requests_or_byte_mismatches": 0,
                },
                sort_keys=True,
            )
        )
