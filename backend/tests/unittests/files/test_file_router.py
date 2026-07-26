from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eneo.database.database import get_session, get_session_with_transaction
from eneo.files import file_router
from eneo.files.file_models import (
    ContentDisposition,
    FileContentRangeError,
    FileContentVariant,
    FileInfo,
    FileMetadata,
    FileType,
    OriginalSignedURLRequest,
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
from tests.fixtures import TEST_USER


def _dependency_calls(route: APIRoute) -> set[object]:
    dependencies = list(route.dependant.dependencies)
    calls: set[object] = set()
    while dependencies:
        dependency = dependencies.pop()
        calls.add(dependency.call)
        dependencies.extend(dependency.dependencies)
    return calls


def test_upload_route_reuses_one_non_transactional_authenticated_container() -> None:
    route = next(
        route
        for route in file_router.router.routes
        if isinstance(route, APIRoute) and route.endpoint is file_router.upload_file
    )

    assert get_session in _dependency_calls(route)
    assert get_session_with_transaction not in _dependency_calls(route)
    assert file_router._require_upload_user_for_creation in {
        dependency.call for dependency in route.dependant.dependencies
    }


def test_upload_request_resolves_shared_container_once_before_file_work() -> None:
    now = datetime.now(UTC)
    saved = FileInfo(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="source.txt",
        checksum="checksum",
        size=7,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        user_id=TEST_USER.id,
        tenant_id=TEST_USER.tenant_id,
    )

    class Session:
        def __init__(self) -> None:
            self.active = False

        def in_transaction(self) -> bool:
            return self.active

        @asynccontextmanager
        async def begin(self):
            assert not self.active
            self.active = True
            try:
                yield
            finally:
                self.active = False

    session = Session()
    file_service = AsyncMock()

    async def save_file(_upload_file):
        assert not session.in_transaction()
        return saved

    file_service.save_file.side_effect = save_file
    audit_service = AsyncMock()
    container = MagicMock()
    container.file_service.return_value = file_service
    container.audit_service.return_value = audit_service
    container.user.return_value = TEST_USER
    container.session.return_value = session
    resolutions = 0

    async def resolve_container():
        nonlocal resolutions
        resolutions += 1
        return container

    app = FastAPI()
    app.include_router(file_router.router)
    app.dependency_overrides[file_router._file_upload_container_dependency] = (
        resolve_container
    )

    response = TestClient(app).post(
        "/",
        files={"upload_file": ("source.txt", b"payload", "text/plain")},
    )

    assert response.status_code == 200, response.text
    assert resolutions == 1
    file_service.save_file.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()


async def test_upload_enqueues_audit_only_after_file_success() -> None:
    events: list[str] = []
    now = datetime.now(UTC)
    user = MagicMock(
        id=uuid4(),
        tenant_id=uuid4(),
        username="file-owner",
        email="owner@example.eu",
    )
    file = FileInfo(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="source.txt",
        checksum="checksum",
        size=7,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        user_id=user.id,
        tenant_id=user.tenant_id,
    )
    service = AsyncMock()

    async def save_file(_upload_file):
        events.append("save")
        return file

    service.save_file.side_effect = save_file
    audit_service = AsyncMock()
    session = MagicMock()

    async def log(**_kwargs):
        events.append("log")

    audit_service.log_async.side_effect = log

    class Container:
        @staticmethod
        def file_service():
            return service

        @staticmethod
        def audit_service():
            return audit_service

        @staticmethod
        def user():
            return user

        @staticmethod
        def session():
            return session

    result = await file_router.upload_file(
        upload_file=MagicMock(),
        container=Container(),
    )

    assert result == file
    assert events == ["save", "log"]
    session.begin.assert_called_once()
    audit_service.log_async.assert_awaited_once()
    audit_service.log.assert_not_awaited()

    service.save_file.side_effect = RuntimeError("upload failed")
    with pytest.raises(RuntimeError, match="upload failed"):
        await file_router.upload_file(
            upload_file=MagicMock(),
            container=Container(),
        )

    audit_service.log_async.assert_awaited_once()


async def test_original_signed_url_audits_the_attributable_access_grant(
    monkeypatch,
):
    file_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)
    metadata = FileMetadata(
        id=file_id,
        created_at=now,
        updated_at=now,
        name="source.pdf",
        file_type=FileType.TEXT,
        mimetype="application/pdf",
        user_id=user_id,
        tenant_id=tenant_id,
    )
    service = AsyncMock()
    service.ensure_original_available.return_value = metadata
    audit_service = AsyncMock()
    user = MagicMock(
        id=user_id,
        tenant_id=tenant_id,
        username="file-owner",
        email="owner@example.eu",
    )

    class Container:
        @staticmethod
        def file_service():
            return service

        @staticmethod
        def audit_service():
            return audit_service

        @staticmethod
        def user():
            return user

    request = MagicMock()
    request.base_url = "https://eneo.example.eu/"
    monkeypatch.setattr(file_router.time, "time", lambda: 1_000)
    monkeypatch.setattr(
        file_router,
        "generate_file_original_download_token",
        lambda **_: "signed",
    )

    response = await file_router.generate_original_signed_url(
        id=file_id,
        request=request,
        signed_url_req=OriginalSignedURLRequest(
            expires_in=120,
            content_disposition=ContentDisposition.ATTACHMENT,
        ),
        container=Container(),
    )

    assert response.expires_at == 1_120
    audit_service.log_async.assert_awaited_once()
    audit = audit_service.log_async.await_args.kwargs
    assert audit["action"].value == "file_original_download_link_created"
    assert audit["entity_id"] == file_id
    assert audit["metadata"]["extra"] == {
        "content_disposition": "attachment",
        "expires_at": 1_120,
        "expires_in_seconds": 120,
    }


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


def test_processing_download_route_uses_a_non_transactional_request_container() -> None:
    route = next(
        route
        for route in file_router.router.routes
        if isinstance(route, APIRoute)
        and route.endpoint is file_router.download_file_signed
    )

    container_dependency = next(
        dependency
        for dependency in route.dependant.dependencies
        if dependency.name == "container"
    )
    assert len(container_dependency.dependencies) == 1
    assert container_dependency.dependencies[0].call is get_session


@pytest.mark.parametrize(
    "method_name",
    ["get_download_no_auth", "get_original_download_no_auth"],
)
async def test_interrupted_download_closes_content_context_once(
    method_name: str,
) -> None:
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

    class Session:
        def __init__(self) -> None:
            self.active = False

        def in_transaction(self) -> bool:
            return self.active

        @asynccontextmanager
        async def begin(self):
            assert not self.active
            self.active = True
            try:
                yield
            finally:
                self.active = False

    session = Session()
    read_context = MagicMock()
    read_context.__aenter__ = AsyncMock()

    async def enter_read_context():
        assert not session.in_transaction()
        return ContentRead(
            chunks=chunks(),
            content_length=6,
            media_type="application/pdf",
            content_range=None,
        )

    read_context.__aenter__.side_effect = enter_read_context
    read_context.__aexit__ = AsyncMock(return_value=None)
    repo = MagicMock()
    repo.session = session

    async def get_by_id(*, file_id):
        assert session.in_transaction()
        return metadata

    async def get_content_references(_file_ids):
        assert session.in_transaction()
        return [reference]

    repo.get_by_id = AsyncMock(side_effect=get_by_id)
    repo.get_content_references = AsyncMock(side_effect=get_content_references)
    object_content = MagicMock()
    object_content.open_content.return_value = read_context
    service = FileService(
        user=None,
        repo=repo,
        protocol=MagicMock(),
        object_content=object_content,
    )

    download = await getattr(service, method_name)(file_id)
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

    for status in ("400", "401", "403", "404", "409", "416", "503"):
        content = operation["responses"][status]["content"]
        schema = content["application/json"]["schema"]
        assert schema["$ref"] == "#/components/schemas/GeneralError"
