from __future__ import annotations

import logging
from io import BytesIO
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import UUID

import pytest
import sqlalchemy as sa
from PIL import Image
from sqlalchemy import select

from eneo.audit.application import audit_service as audit_service_module
from eneo.database.database import sessionmanager
from eneo.database.tables.feature_flag_table import GlobalFeatureFlag
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.object_content.content import StorageKind
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.runtime import object_content_runtime


def _opaque_png(*, width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(24, 95, 180)).save(
        buffer,
        format="PNG",
    )
    return buffer.getvalue()


class _ReadyObjectStoreContentService(ObjectContentService):
    async def ensure_target_ready(self, storage_kind: StorageKind) -> None:
        assert storage_kind is StorageKind.OBJECT_STORE


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_target",
    [StorageKind.POSTGRES_INLINE, StorageKind.OBJECT_STORE],
)
async def test_file_upload_respects_audit_kill_switch_after_storage_commit(
    client,
    db_container,
    admin_user_api_key,
    real_object_store,
    monkeypatch,
    caplog,
    storage_target: StorageKind,
) -> None:
    async with db_container() as container:
        session = container.session()
        policy = await session.get(ObjectContentDeploymentPolicy, 1)
        assert policy is not None
        policy.new_write_storage_target = storage_target.value

    if storage_target is StorageKind.OBJECT_STORE:
        monkeypatch.setattr(
            object_content_runtime,
            "_service",
            _ReadyObjectStoreContentService(
                real_object_store.settings,
                sessionmanager,
                object_store_settings=real_object_store.settings,
                object_store=real_object_store.store,
            ),
        )

    enqueue = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    caplog.set_level(logging.WARNING, logger=audit_service_module.__name__)

    headers = {"X-API-Key": admin_user_api_key.key}
    for audit_enabled in (False, True):
        async with db_container() as container:
            session = container.session()
            audit_flag = await session.scalar(
                select(GlobalFeatureFlag).where(
                    GlobalFeatureFlag.name == "audit_logging_enabled"
                )
            )
            assert audit_flag is not None
            audit_flag.enabled = audit_enabled

        enqueue.reset_mock()
        caplog.clear()
        upload = await client.post(
            "/api/v1/files/",
            files={
                "upload_file": (
                    f"audit-{storage_target.value}-{audit_enabled}.txt",
                    b"audited payload",
                    "text/plain",
                )
            },
            headers=headers,
        )

        assert upload.status_code == 200, upload.text
        file_upload_enqueues = [
            call
            for call in enqueue.await_args_list
            if call.args[2]["action"] == "file_uploaded"
        ]
        assert len(file_upload_enqueues) == int(audit_enabled)
        assert "Failed to check audit_logging_enabled flag" not in caplog.text

        deletion = await client.delete(
            f"/api/v1/files/{upload.json()['id']}/",
            headers=headers,
        )
        assert deletion.status_code == 204, deletion.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_used_file_delete_returns_the_typed_preview_before_mutation(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("policy.txt", b"durable policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = UUID(upload.json()["id"])

    async with db_container() as container:
        user = container.user()
        session = container.session()
        chat_session = Sessions(user_id=user.id, name="Deletion preview")
        session.add(chat_session)
        await session.flush()
        question = Questions(
            question="Use the policy",
            answer="",
            num_tokens_question=0,
            num_tokens_answer=0,
            tenant_id=user.tenant_id,
            session_id=chat_session.id,
        )
        session.add(question)
        await session.flush()
        question_id = question.id
        session.add(
            QuestionsFiles(
                question_id=question_id,
                file_id=file_id,
                type="user",
            )
        )

    expected_preview = {
        "file_id": str(file_id),
        "can_delete": False,
        "affected_file_count": 1,
        "blockers": [{"kind": "chat_attachment", "count": 1}],
    }
    preview = await client.get(
        f"/api/v1/files/{file_id}/deletion-preview/",
        headers=headers,
    )
    deletion = await client.delete(
        f"/api/v1/files/{file_id}/",
        headers=headers,
    )

    assert preview.status_code == 200, preview.text
    assert preview.json() == expected_preview
    assert deletion.status_code == 409, deletion.text
    assert deletion.json()["code"] == "file_in_use"
    assert deletion.json()["eneo_error_code"] == 9044
    assert deletion.json()["details"] == expected_preview

    async with db_container() as container:
        session = container.session()
        assert await session.get(QuestionsFiles, (question_id, file_id)) is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_metadata_routes_preserve_persisted_transcription(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("meeting.mp3", b"audio", "audio/mpeg")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = UUID(upload.json()["id"])

    async with db_container() as container:
        saved = await container.file_service().save_transcription(
            file_id,
            "durable transcript",
        )
        assert saved == "durable transcript"

    single = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
    listing = await client.get("/api/v1/files/", headers=headers)

    assert single.status_code == 200, single.text
    assert listing.status_code == 200, listing.text
    assert single.json()["transcription"] == "durable transcript"
    listed = next(
        item for item in listing.json()["items"] if item["id"] == str(file_id)
    )
    assert listed["transcription"] == "durable transcript"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_listing_batches_multiple_transcriptions_in_one_payload_query(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    file_ids: list[UUID] = []
    for index in range(3):
        upload = await client.post(
            "/api/v1/files/",
            files={
                "upload_file": (
                    f"meeting-{index}.mp3",
                    f"audio-{index}".encode(),
                    "audio/mpeg",
                )
            },
            headers=headers,
        )
        assert upload.status_code == 200, upload.text
        file_ids.append(UUID(upload.json()["id"]))

    async with db_container() as container:
        for index, file_id in enumerate(file_ids):
            saved = await container.file_service().save_transcription(
                file_id,
                f"durable transcript {index}",
            )
            assert saved == f"durable transcript {index}"

        session = container.session()
        assert session.bind is not None
        sync_engine = session.bind.sync_engine

    inline_payload_queries: list[str] = []

    def capture_inline_payload_query(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "inline_content_payloads" in statement.lower():
            inline_payload_queries.append(statement)

    sa.event.listen(
        sync_engine,
        "before_cursor_execute",
        capture_inline_payload_query,
    )
    try:
        listing = await client.get("/api/v1/files/", headers=headers)
    finally:
        sa.event.remove(
            sync_engine,
            "before_cursor_execute",
            capture_inline_payload_query,
        )

    assert listing.status_code == 200, listing.text
    listed = {
        UUID(item["id"]): item["transcription"] for item in listing.json()["items"]
    }
    assert [listed[file_id] for file_id in file_ids] == [
        "durable transcript 0",
        "durable transcript 1",
        "durable transcript 2",
    ]
    assert len(inline_payload_queries) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_signed_download_rejects_corrupt_content_before_success_headers(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    payload = b"durable policy"
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("policy.txt", payload, "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = UUID(upload.json()["id"])
    signed = await client.post(
        f"/api/v1/files/{file_id}/signed-url/",
        json={"content_disposition": "attachment"},
        headers=headers,
    )
    assert signed.status_code == 200, signed.text

    async with db_container() as container:
        session = container.session()
        content_id = await session.scalar(
            select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id,
                FileContentReferences.variant == "extracted_text",
            )
        )
        assert content_id is not None
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        stored = await session.get(InlineContentPayloads, content_id)
        assert stored is not None
        stored.payload = b"x" * len(stored.payload)

    download_url = signed.json()["url"]
    download = await client.get(
        f"{urlsplit(download_url).path}?{urlsplit(download_url).query}"
    )

    assert download.status_code == 503
    assert download.headers["content-type"].startswith("application/json")
    assert download.json()["code"] == "object_content_integrity_failure"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_image_metadata_matches_the_selected_download_representation(
    client,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    source = _opaque_png(width=2049, height=16)
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("wide.png", source, "image/png")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()
    file_id = uploaded["id"]

    single = await client.get(f"/api/v1/files/{file_id}/", headers=headers)
    listing = await client.get("/api/v1/files/", headers=headers)
    signed = await client.post(
        f"/api/v1/files/{file_id}/signed-url/",
        json={"content_disposition": "attachment"},
        headers=headers,
    )

    assert single.status_code == 200, single.text
    assert listing.status_code == 200, listing.text
    assert signed.status_code == 200, signed.text
    listed = next(item for item in listing.json()["items"] if item["id"] == file_id)
    download_url = signed.json()["url"]
    download = await client.get(
        f"{urlsplit(download_url).path}?{urlsplit(download_url).query}"
    )
    assert download.status_code == 200, download.text

    for metadata in (uploaded, single.json(), listed):
        assert metadata["mimetype"] == "image/jpeg"
        assert metadata["size"] == len(download.content)
    assert download.headers["content-type"] == "image/jpeg"
    assert int(download.headers["content-length"]) == len(download.content)
