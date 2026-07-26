from __future__ import annotations

import base64
import time
from collections.abc import AsyncGenerator
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from botocore.config import Config
from botocore.session import get_session
from sqlalchemy import select

from eneo.authentication.signed_urls import (
    generate_file_original_download_token,
)
from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectStoreObjects,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.files import file_router
from eneo.files.file_models import ContentDisposition, FileContentVariant, FileType
from eneo.files.file_protocol import PendingFileContent, PreparedFileUpload
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.s3_object_store import S3ObjectStore
from tests.integration.object_content.conftest import RealObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import (
        GetObjectOutputTypeDef,
        GetObjectRequestTypeDef,
    )


class _RecordingRangeClient:
    def __init__(self, delegate: S3Client) -> None:
        self._delegate = delegate
        self.requests: list[tuple[str | None, int]] = []

    def get_object(self, **request: object) -> GetObjectOutputTypeDef:
        result = self._delegate.get_object(**cast("GetObjectRequestTypeDef", request))
        self.requests.append(
            (
                cast(str | None, request.get("Range")),
                cast(int, result["ContentLength"]),
            )
        )
        return result

    def close(self) -> None:
        self._delegate.close()


async def _bytes_source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


async def _persist_prepared(db_container, prepared: PreparedFileUpload) -> UUID:
    async with db_container() as container:
        return await container.file_service()._persist_prepared_file(prepared)


async def _signed_download(client, headers, file_id: UUID, *, original: bool):
    segment = "original/" if original else ""
    signed = await client.post(
        f"/api/v1/files/{file_id}/{segment}signed-url/",
        json={"content_disposition": "attachment"},
        headers=headers,
    )
    assert signed.status_code == 200, signed.text
    parsed = urlsplit(signed.json()["url"])
    return await client.get(f"{parsed.path}?{parsed.query}")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "media_type", "original"),
    [
        ("report.pdf", "application/pdf", b"%PDF exact original"),
        (
            "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK exact docx original",
        ),
    ],
)
async def test_original_text_download_does_not_fall_back_to_extracted_text(
    client,
    db_container,
    admin_user_api_key,
    name: str,
    media_type: str,
    original: bytes,
) -> None:
    extracted = b"searchable extracted text"
    file_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name=name,
            file_type=FileType.TEXT,
            display_media_type=media_type,
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(original),
                    declared_media_type=media_type,
                    verified_media_type=media_type,
                ),
                PendingFileContent(
                    variant=FileContentVariant.EXTRACTED_TEXT,
                    chunks=_bytes_source(extracted),
                    declared_media_type="text/plain",
                    verified_media_type="text/plain",
                ),
            ),
        ),
    )
    headers = {"X-API-Key": admin_user_api_key.key}

    processing = await _signed_download(
        client,
        headers,
        file_id,
        original=False,
    )
    downloaded = await _signed_download(
        client,
        headers,
        file_id,
        original=True,
    )

    assert processing.content == extracted
    assert processing.headers["content-type"] == "text/plain; charset=utf-8"
    assert downloaded.status_code == 200
    assert downloaded.content == original
    assert downloaded.headers["content-type"] == media_type
    assert downloaded.headers["content-disposition"].endswith(f'filename="{name}"')
    digest = base64.b64encode(sha256(original).digest()).decode("ascii")
    assert downloaded.headers["repr-digest"] == f"sha-256=:{digest}:"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_image_and_audio_ranges_preserve_exact_bytes(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    image_original = b"large original image"
    image_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name="photo.png",
            file_type=FileType.IMAGE,
            display_media_type="image/png",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(image_original),
                    declared_media_type="image/png",
                    verified_media_type="image/png",
                ),
                PendingFileContent(
                    variant=FileContentVariant.MODEL_INPUT,
                    chunks=_bytes_source(b"bounded model image"),
                    declared_media_type="image/jpeg",
                    verified_media_type="image/jpeg",
                ),
            ),
        ),
    )
    audio = b"0123456789"
    audio_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name="meeting.mp3",
            file_type=FileType.AUDIO,
            display_media_type="audio/mpeg",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(audio),
                    declared_media_type="audio/mpeg",
                    verified_media_type="audio/mpeg",
                ),
            ),
        ),
    )
    headers = {"X-API-Key": admin_user_api_key.key}

    image_processing = await _signed_download(
        client,
        headers,
        image_id,
        original=False,
    )
    image_download = await _signed_download(
        client,
        headers,
        image_id,
        original=True,
    )
    signed = await client.post(
        f"/api/v1/files/{audio_id}/original/signed-url/",
        json={},
        headers=headers,
    )
    parsed = urlsplit(signed.json()["url"])
    audio_range = await client.get(
        f"{parsed.path}?{parsed.query}",
        headers={"Range": "bytes=3-6"},
    )
    invalid_range = await client.get(
        f"{parsed.path}?{parsed.query}",
        headers={"Range": "bytes=99-"},
    )

    assert image_processing.content == b"bounded model image"
    assert image_download.content == image_original
    assert image_download.headers["content-type"] == "image/png"
    assert "accept-ranges" not in image_download.headers
    assert audio_range.status_code == 206
    assert audio_range.content == audio[3:7]
    assert audio_range.headers["content-range"] == f"bytes 3-6/{len(audio)}"
    assert audio_range.headers["accept-ranges"] == "bytes"
    assert invalid_range.status_code == 416
    assert invalid_range.headers["content-range"] == f"bytes */{len(audio)}"
    assert invalid_range.json()["eneo_error_code"] == 9007


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_original_is_typed_and_never_falls_back(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    file_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name="legacy.pdf",
            file_type=FileType.TEXT,
            display_media_type="application/pdf",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.EXTRACTED_TEXT,
                    chunks=_bytes_source(b"legacy extracted text"),
                    declared_media_type="text/plain",
                    verified_media_type="text/plain",
                ),
            ),
        ),
    )

    response = await client.post(
        f"/api/v1/files/{file_id}/original/signed-url/",
        json={},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "file_original_not_found"
    assert response.json()["eneo_error_code"] == 9045
    assert response.json()["message"] == (
        "The exact original is not available for this file."
    )

    token = generate_file_original_download_token(
        file_id=file_id,
        expires_at=int(time.time()) + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
    )
    download = await client.get(
        f"/api/v1/files/{file_id}/original/download/",
        params={"token": token},
    )
    assert download.status_code == 404
    assert download.json()["code"] == "file_original_not_found"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_mint_does_not_read_payload_and_corruption_fails_before_headers(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    payload = b"exact original"
    file_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name="record.pdf",
            file_type=FileType.TEXT,
            display_media_type="application/pdf",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(payload),
                    declared_media_type="application/pdf",
                    verified_media_type="application/pdf",
                ),
            ),
        ),
    )
    headers = {"X-API-Key": admin_user_api_key.key}
    async with db_container() as container:
        session = container.session()
        assert session.bind is not None
        engine = session.bind.sync_engine

    payload_queries: list[str] = []

    def capture_payload_query(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "inline_content_payloads" in statement.lower():
            payload_queries.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture_payload_query)
    try:
        signed = await client.post(
            f"/api/v1/files/{file_id}/original/signed-url/",
            json={},
            headers=headers,
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture_payload_query)

    assert signed.status_code == 200, signed.text
    assert payload_queries == []

    async with db_container() as container:
        session = container.session()
        content_id = await session.scalar(
            select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file_id,
                FileContentReferences.variant == FileContentVariant.ORIGINAL.value,
            )
        )
        assert content_id is not None
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        stored = await session.get(InlineContentPayloads, content_id)
        assert stored is not None
        stored.payload = b"x" * len(stored.payload)

    parsed = urlsplit(signed.json()["url"])
    download = await client.get(f"{parsed.path}?{parsed.query}")

    assert download.status_code == 503
    assert download.headers["content-type"].startswith("application/json")
    assert download.json()["code"] == "object_content_integrity_failure"

    retry = await client.get(f"{parsed.path}?{parsed.query}")

    assert retry.status_code == 404
    assert retry.headers["content-type"].startswith("application/json")
    assert retry.json()["eneo_error_code"] == 9000
    assert "code" not in retry.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_signed_url_enforces_short_lived_expiry(
    client,
    db_container,
    admin_user_api_key,
) -> None:
    file_id = await _persist_prepared(
        db_container,
        PreparedFileUpload(
            name="source.pdf",
            file_type=FileType.TEXT,
            display_media_type="application/pdf",
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.ORIGINAL,
                    chunks=_bytes_source(b"exact source"),
                    declared_media_type="application/pdf",
                    verified_media_type="application/pdf",
                ),
            ),
        ),
    )
    headers = {"X-API-Key": admin_user_api_key.key}

    maximum = await client.post(
        f"/api/v1/files/{file_id}/original/signed-url/",
        json={"expires_in": 3600},
        headers=headers,
    )

    assert maximum.status_code == 200, maximum.text
    for invalid_expiry in (0, -1, 3601):
        rejected = await client.post(
            f"/api/v1/files/{file_id}/original/signed-url/",
            json={"expires_in": invalid_expiry},
            headers=headers,
        )
        assert rejected.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_original_audio_range_reads_only_verified_chunks_from_real_store(
    object_content_database: DatabaseSessionManager,
    real_object_store: RealObjectStore,
) -> None:
    settings = real_object_store.settings
    payload = b"a" * settings.multipart_part_bytes + b"verified-range-tail"
    content_service = ObjectContentService(
        settings,
        object_content_database,
        object_store_settings=settings,
        object_store=real_object_store.store,
    )
    prepared_id: UUID | None = None
    object_key: str | None = None
    read_store: S3ObjectStore | None = None

    try:
        async with capture_content(
            _bytes_source(payload),
            declared_media_type="audio/mpeg",
            verified_media_type="audio/mpeg",
            maximum_size_bytes=len(payload),
            spool_memory_bytes=settings.spool_memory_bytes,
            multipart_part_bytes=settings.multipart_part_bytes,
        ) as captured:
            async with (
                object_content_database.session() as session,
                session.begin(),
            ):
                tenant_id = (await session.scalars(select(Tenants.id))).one()
                user_id = (await session.scalars(select(Users.id))).one()
                owner = Files(
                    name=f"{uuid4().hex}.mp3",
                    mimetype="audio/mpeg",
                    file_type=FileType.AUDIO.value,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    parent_file_id=None,
                )
                session.add(owner)
                await session.flush()
                file_id = owner.id
                prepared = await content_service.prepare_in_transaction(
                    session,
                    intent=ContentIntent(
                        tenant_id=tenant_id,
                        created_by_user_id=user_id,
                        access_class=ContentAccessClass.PRIVATE_RESOURCE,
                        idempotency_key=uuid4().hex,
                        producer_receipt=f"file:{file_id}:original:0",
                    ),
                    content=captured,
                    storage_kind=StorageKind.OBJECT_STORE,
                )
                prepared_id = prepared.id
                session.add(
                    FileContentReferences(
                        file_id=file_id,
                        content_id=prepared.id,
                        variant=FileContentVariant.ORIGINAL.value,
                        ordinal=0,
                    )
                )

            await content_service.store_and_verify(
                content_id=prepared.id,
                content=captured,
            )

        async with object_content_database.session() as session:
            async with session.begin():
                descriptor = await session.get(ObjectStoreObjects, prepared.id)
                assert descriptor is not None
                object_key = descriptor.object_key

            raw_client = cast(
                "S3Client",
                get_session().create_client(
                    "s3",
                    endpoint_url=settings.endpoint_url,
                    region_name=settings.region,
                    aws_access_key_id=settings.access_key_id.get_secret_value(),
                    aws_secret_access_key=(
                        settings.secret_access_key.get_secret_value()
                    ),
                    verify=(
                        str(settings.ca_bundle)
                        if settings.ca_bundle is not None
                        else True
                    ),
                    config=Config(
                        signature_version="s3v4",
                        s3={"addressing_style": settings.addressing_style},
                    ),
                ),
            )
            recording_client = _RecordingRangeClient(raw_client)
            read_store = S3ObjectStore(
                settings,
                client=cast("S3Client", recording_client),
            )
            read_content_service = ObjectContentService(
                settings,
                object_content_database,
                object_store_settings=settings,
                object_store=read_store,
            )
            checked_content_service = MagicMock(wraps=read_content_service)

            def open_without_file_transaction(*args, **kwargs):
                assert not session.in_transaction()
                return read_content_service.open_content(*args, **kwargs)

            checked_content_service.open_content.side_effect = (
                open_without_file_transaction
            )
            service = FileService(
                user=None,
                repo=FileRepository(session),
                protocol=MagicMock(),
                object_content=checked_content_service,
            )

            class Container:
                @staticmethod
                def file_service(*, user):
                    assert user is None
                    return service

            token = generate_file_original_download_token(
                file_id=file_id,
                expires_at=int(time.time()) + 60,
                content_disposition=ContentDisposition.ATTACHMENT,
            )
            response = await file_router.download_original_file_signed(
                id=file_id,
                token=token,
                range=(
                    f"bytes={settings.multipart_part_bytes + 1}-"
                    f"{settings.multipart_part_bytes + 5}"
                ),
                container=Container(),
            )
            body_parts: list[bytes] = []
            async for chunk in response.body_iterator:
                assert isinstance(chunk, bytes)
                body_parts.append(chunk)
            body = b"".join(body_parts)

        digest = base64.b64encode(sha256(payload).digest()).decode("ascii")
        assert response.status_code == 206
        assert (
            body
            == payload[
                settings.multipart_part_bytes + 1 : settings.multipart_part_bytes + 6
            ]
        )
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.headers["content-length"] == "5"
        assert response.headers["content-range"] == (
            f"bytes {settings.multipart_part_bytes + 1}-"
            f"{settings.multipart_part_bytes + 5}/{len(payload)}"
        )
        assert response.headers["repr-digest"] == f"sha-256=:{digest}:"
        assert recording_client.requests == [
            (
                f"bytes={settings.multipart_part_bytes}-{len(payload) - 1}",
                len(payload) - settings.multipart_part_bytes,
            )
        ]
    finally:
        if read_store is not None:
            await read_store.close()
        if object_key is None and prepared_id is not None:
            async with (
                object_content_database.session() as session,
                session.begin(),
            ):
                descriptor = await session.get(ObjectStoreObjects, prepared_id)
                if descriptor is not None:
                    object_key = descriptor.object_key
        if object_key is not None:
            await real_object_store.store.delete_and_confirm(object_key)
