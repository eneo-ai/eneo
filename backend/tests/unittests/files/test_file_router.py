from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from eneo.files import file_router
from eneo.files.file_models import (
    ContentDisposition,
    FileContentRangeError,
    FileContentVariant,
    FileMetadata,
    FileType,
)
from eneo.files.file_repo import FileContentReferenceRecord
from eneo.files.file_service import FileDownload, FileService
from eneo.main.exceptions import (
    AuthenticationException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.object_content.content import (
    ContentAccessClass,
    ContentRead,
)


async def test_download_file_signed_raises_not_found_for_missing_content(monkeypatch):
    file_id = uuid4()
    payload = {
        "file_id": str(file_id),
        "content_disposition": "inline",
    }

    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    service = AsyncMock()
    service.get_download_no_auth.side_effect = NotFoundException(
        "File content not found"
    )

    class Container:
        @staticmethod
        def file_service(*, user):
            assert user is None
            return service

    with pytest.raises(NotFoundException, match="File content not found"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=Container()
        )


async def test_original_download_rejects_processing_token(monkeypatch):
    file_id = uuid4()
    monkeypatch.setattr(
        file_router,
        "verify_file_original_download_token",
        lambda _: None,
    )

    with pytest.raises(AuthenticationException, match="Invalid or expired token"):
        await file_router.download_original_file_signed(
            id=file_id,
            token="token",
            range=None,
            container=object(),
        )


async def test_original_download_rejects_token_for_another_file(monkeypatch):
    requested_file_id = uuid4()
    monkeypatch.setattr(
        file_router,
        "verify_file_original_download_token",
        lambda _: {
            "file_id": str(uuid4()),
            "content_disposition": "attachment",
        },
    )

    with pytest.raises(UnauthorizedException, match="not valid for this file"):
        await file_router.download_original_file_signed(
            id=requested_file_id,
            token="token",
            range=None,
            container=object(),
        )


async def test_unsatisfiable_original_range_uses_known_size_without_reopening(
    monkeypatch,
):
    file_id = uuid4()
    monkeypatch.setattr(
        file_router,
        "verify_file_original_download_token",
        lambda _: {
            "file_id": str(file_id),
            "content_disposition": "attachment",
        },
    )
    service = AsyncMock()
    service.get_original_download_no_auth.side_effect = FileContentRangeError(
        "not satisfiable",
        total_size=321,
    )

    class Container:
        @staticmethod
        def file_service(*, user):
            assert user is None
            return service

    response = await file_router.download_original_file_signed(
        id=file_id,
        token="token",
        range="bytes=999-",
        container=Container(),
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */321"
    assert response.body
    assert b'"eneo_error_code":9007' in response.body
    service.get_original_download_no_auth.assert_awaited_once_with(
        file_id,
        range_header="bytes=999-",
    )


async def test_legacy_unsatisfiable_range_preserves_empty_response(monkeypatch):
    file_id = uuid4()
    monkeypatch.setattr(
        file_router,
        "verify_signed_token",
        lambda _: {
            "file_id": str(file_id),
            "content_disposition": "attachment",
        },
    )
    service = AsyncMock()
    service.get_download_no_auth.side_effect = FileContentRangeError(
        "not satisfiable",
        total_size=654,
    )

    class Container:
        @staticmethod
        def file_service(*, user):
            assert user is None
            return service

    response = await file_router.download_file_signed(
        id=file_id,
        token="token",
        range="bytes=999-",
        container=Container(),
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */654"
    assert response.body == b""


async def test_interrupted_original_download_closes_content_context_once():
    file_id = uuid4()
    content_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)
    metadata = FileMetadata(
        id=file_id,
        created_at=now,
        updated_at=now,
        name="report.pdf",
        file_type=FileType.TEXT,
        mimetype="application/pdf",
        user_id=user_id,
        tenant_id=tenant_id,
    )
    reference = FileContentReferenceRecord(
        file_id=file_id,
        content_id=content_id,
        variant=FileContentVariant.ORIGINAL,
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=b"x" * 32,
        size_bytes=6,
        media_type="application/pdf",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
    )

    async def chunks() -> AsyncGenerator[bytes]:
        yield b"abc"
        yield b"def"

    read_context = MagicMock()
    read_context.__aenter__ = AsyncMock(
        return_value=ContentRead(
            chunks=chunks(),
            content_length=6,
            media_type="application/pdf",
            content_range=None,
        )
    )
    read_context.__aexit__ = AsyncMock(return_value=None)
    repo = MagicMock()
    repo.session = MagicMock()
    repo.get_by_id = AsyncMock(return_value=metadata)
    repo.get_content_references = AsyncMock(return_value=[reference])
    object_content = MagicMock()
    object_content.open_content.return_value = read_context
    service = FileService(
        user=None,
        repo=repo,
        protocol=MagicMock(),
        object_content=object_content,
    )

    download = await service.get_original_download_no_auth(file_id)
    assert await anext(download.chunks) == b"abc"
    await download.chunks.aclose()
    await download.aclose()
    await download.aclose()

    read_context.__aexit__.assert_awaited_once()


async def test_download_response_preserves_safe_ascii_filename_and_closes_once():
    closed = AsyncMock()

    async def chunks() -> AsyncGenerator[bytes]:
        yield b"content"

    response = file_router._download_response(
        FileDownload(
            chunks=chunks(),
            content_length=7,
            media_type="application/pdf",
            filename="quarterly report.pdf",
            sha256=b"x" * 32,
            content_range=None,
            range_supported=False,
            _close=closed,
        ),
        content_disposition=ContentDisposition.ATTACHMENT,
    )

    assert response.headers["content-disposition"] == (
        'attachment; filename="quarterly report.pdf"'
    )
    assert "accept-ranges" not in response.headers
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"content"
    await response.body_iterator.aclose()
    await response.body_iterator.aclose()
    closed.assert_awaited_once()


@pytest.mark.parametrize(
    "filename",
    [
        "räksmörgås.pdf",
        'report "final".pdf',
        "report\\draft.pdf",
        "report\r\nX-Injected: yes.pdf",
        "\x01report.pdf",
    ],
)
async def test_download_response_safely_encodes_untrusted_filename(filename: str):
    closed = AsyncMock()

    async def chunks() -> AsyncGenerator[bytes]:
        yield b"content"

    response = file_router._download_response(
        FileDownload(
            chunks=chunks(),
            content_length=7,
            media_type="application/pdf",
            filename=filename,
            sha256=b"x" * 32,
            content_range=None,
            range_supported=False,
            _close=closed,
        ),
        content_disposition=ContentDisposition.ATTACHMENT,
    )
    header = response.headers["content-disposition"]

    assert "\r" not in header
    assert "\n" not in header
    assert "filename=" in header
    assert "filename*=UTF-8''" in header
    assert await anext(response.body_iterator) == b"content"
    await response.body_iterator.aclose()
    closed.assert_awaited_once()


async def test_audio_download_advertises_range_support():
    async def chunks() -> AsyncGenerator[bytes]:
        yield b"audio"

    response = file_router._download_response(
        FileDownload(
            chunks=chunks(),
            content_length=5,
            media_type="audio/mpeg",
            filename="meeting.mp3",
            sha256=b"x" * 32,
            content_range=None,
            range_supported=True,
            _close=AsyncMock(),
        ),
        content_disposition=ContentDisposition.INLINE,
    )

    assert response.headers["accept-ranges"] == "bytes"
    await response.body_iterator.aclose()


def test_original_download_openapi_declares_json_error_contracts():
    app = FastAPI()
    app.include_router(file_router.router)
    operation = app.openapi()["paths"]["/{id}/original/download/"]["get"]

    for status in ("400", "401", "403", "404", "416", "503"):
        content = operation["responses"][status]["content"]
        schema = content["application/json"]["schema"]
        assert schema["$ref"] == "#/components/schemas/GeneralError"
