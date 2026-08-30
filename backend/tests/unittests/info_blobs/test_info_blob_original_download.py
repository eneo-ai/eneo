from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eneo.files.file_models import ContentDisposition, OriginalSignedURLRequest
from eneo.info_blobs import info_blobs_router
from eneo.info_blobs.info_blob import (
    InfoBlobInDB,
    InfoBlobOriginalUnavailableError,
    InfoBlobPublic,
)
from eneo.info_blobs.info_blob_protocol import to_info_blob_public
from eneo.info_blobs.info_blob_repo import InfoBlobOriginal
from eneo.info_blobs.info_blob_service import InfoBlobService
from eneo.main.exceptions import UnauthorizedException
from eneo.object_content.content import ContentAccessClass, ContentState
from eneo.questions.question import Question
from eneo.questions.question_protocol import to_question_public
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.protocol.downloads import content_disposition_header


def _info_blob(*, original_available: bool | None) -> InfoBlobInDB:
    return InfoBlobInDB(
        id=uuid4(),
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=10,
        source_id=uuid4(),
        version_state="active",
        text="Extracted text",
        original_available=original_available,
    )


class _Session:
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


async def _open_download(chunks: AsyncGenerator[bytes, None]):
    tenant_id = uuid4()
    repo = MagicMock(session=_Session())
    repo.get_original = AsyncMock(
        return_value=InfoBlobOriginal(
            content_id=uuid4(),
            tenant_id=tenant_id,
            sha256=b"x" * 32,
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
            state=ContentState.AVAILABLE,
            original_filename="source.pdf",
        )
    )
    read_context = MagicMock()
    read_context.__aenter__ = AsyncMock(
        return_value=SimpleNamespace(
            chunks=chunks,
            content_length=10,
            media_type="application/pdf",
        )
    )
    read_context.__aexit__ = AsyncMock(return_value=None)
    object_content = MagicMock()
    object_content.open_content.return_value = read_context
    service = InfoBlobService(
        repo=repo,
        space_repo=AsyncMock(),
        user=MagicMock(),
        quota_service=AsyncMock(),
        group_service=AsyncMock(),
        update_website_size_service=AsyncMock(),
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
        datastore=AsyncMock(),
        object_content=object_content,
    )
    download = await service.get_original_download_no_auth(
        uuid4(), expected_tenant_id=tenant_id
    )
    return download, read_context


def test_claim_validation_checks_blob_id_and_returns_tenant(monkeypatch):
    blob_id, tenant_id = uuid4(), uuid4()
    monkeypatch.setattr(
        info_blobs_router,
        "verify_info_blob_original_download_token",
        lambda _: {
            "info_blob_id": str(blob_id),
            "tenant_id": str(tenant_id),
            "content_disposition": "inline",
        },
    )
    disposition, claimed_tenant = info_blobs_router._validate_original_claims(
        blob_id, "token"
    )
    assert disposition is ContentDisposition.INLINE
    assert claimed_tenant == tenant_id
    with pytest.raises(UnauthorizedException):
        info_blobs_router._validate_original_claims(uuid4(), "token")


@pytest.mark.parametrize("filename", ["rapport 2026.pdf", "årsrapport.pdf"])
def test_content_disposition_is_ascii_safe(filename):
    value = content_disposition_header(ContentDisposition.ATTACHMENT.value, filename)
    assert all(ord(char) < 128 for char in value)
    if not filename.isascii():
        assert "filename*=UTF-8''" in value


@pytest.mark.asyncio
async def test_mint_audit_metadata_excludes_token(monkeypatch):
    blob_id, tenant_id = uuid4(), uuid4()
    actor = MagicMock(id=uuid4(), tenant_id=tenant_id, username="admin", email="a@x.se")
    blob = MagicMock(id=blob_id, tenant_id=tenant_id)
    service, audit = AsyncMock(), AsyncMock()
    service.ensure_original_available.return_value = blob
    monkeypatch.setattr(info_blobs_router.time, "time", lambda: 1_000)
    monkeypatch.setattr(
        info_blobs_router,
        "generate_info_blob_original_download_token",
        lambda **_: "secret-token",
    )

    class Container:
        info_blob_service = staticmethod(lambda: service)
        user = staticmethod(lambda: actor)
        audit_service = staticmethod(lambda: audit)

    await info_blobs_router.generate_original_signed_url(
        id=blob_id,
        request=MagicMock(
            url_for=MagicMock(
                return_value=f"https://eneo.example/api/v1/info-blobs/{blob_id}/original/download/"
            )
        ),
        signed_url_req=OriginalSignedURLRequest(
            expires_in=120, content_disposition=ContentDisposition.INLINE
        ),
        container=Container(),
    )
    metadata = audit.log_async.await_args.kwargs["metadata"]
    assert metadata["actor"]["id"] == str(actor.id)
    assert metadata["target"]["id"] == str(blob_id)
    assert metadata["extra"]["expires_at"] == 1_120
    assert metadata["extra"]["content_disposition"] == "inline"
    assert "secret-token" not in str(metadata)


@pytest.mark.asyncio
async def test_download_sets_digest_and_unicode_filename_headers(monkeypatch):
    blob_id, tenant_id = uuid4(), uuid4()
    monkeypatch.setattr(
        info_blobs_router,
        "verify_info_blob_original_download_token",
        lambda _: {
            "info_blob_id": str(blob_id),
            "tenant_id": str(tenant_id),
            "content_disposition": "attachment",
        },
    )

    async def chunks() -> AsyncIterator[bytes]:
        yield b"original"

    download = MagicMock(
        chunks=chunks(),
        content_length=8,
        media_type="application/pdf",
        filename="årsrapport.pdf",
        sha256=b"hash",
        aclose=AsyncMock(),
    )
    service = AsyncMock()
    service.get_original_download_no_auth.return_value = download

    class Container:
        @staticmethod
        def info_blob_service(user):
            assert user is None
            return service

    response = await info_blobs_router.download_original(blob_id, "token", Container())
    assert response.headers["repr-digest"] == "sha-256=:aGFzaA==:"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    await response.aclose()
    download.aclose.assert_awaited_once_with()


def test_unavailable_original_is_typed_not_found():
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/original")
    async def original():
        raise InfoBlobOriginalUnavailableError()

    response = TestClient(app, raise_server_exceptions=False).get("/original")
    assert response.status_code == 404
    assert response.json()["code"] == "info_blob_original_unavailable"


def test_public_info_blob_requires_derived_original_availability():
    schema = InfoBlobPublic.model_json_schema()

    assert "original_available" in schema["required"]
    assert "default" not in schema["properties"]["original_available"]


def test_unprojected_original_availability_fails_public_serialization():
    with pytest.raises(ValidationError):
        to_info_blob_public(_info_blob(original_available=None))


def test_nested_question_serializes_projected_original_availability():
    question = Question(
        id=uuid4(),
        question="What is in the sources?",
        answer="An answer",
        num_tokens_question=1,
        num_tokens_answer=1,
        tenant_id=uuid4(),
        session_id=uuid4(),
        info_blobs=[
            _info_blob(original_available=True),
            _info_blob(original_available=False),
        ],
    )

    public = to_question_public(question)

    assert [reference.original_available for reference in public.references] == [
        True,
        False,
    ]


@pytest.mark.asyncio
async def test_original_stream_forwards_failure_to_content_context_once():
    failure = RuntimeError("stream failed")

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"first"
        raise failure

    download, read_context = await _open_download(chunks())

    assert await anext(download.chunks) == b"first"
    with pytest.raises(RuntimeError, match="stream failed"):
        await anext(download.chunks)
    await download.aclose()

    read_context.__aexit__.assert_awaited_once()
    exception_type, exception, traceback = read_context.__aexit__.await_args.args
    assert exception_type is RuntimeError
    assert exception is failure
    assert traceback is not None


@pytest.mark.asyncio
async def test_original_download_closes_before_iteration_once():
    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"unused"

    download, read_context = await _open_download(chunks())

    await download.aclose()
    await download.aclose()

    read_context.__aexit__.assert_awaited_once_with(None, None, None)


def test_original_download_openapi_declares_json_error_contracts():
    app = FastAPI()
    app.include_router(info_blobs_router.router)
    operation = app.openapi()["paths"]["/{id}/original/download/"]["get"]

    success = operation["responses"]["200"]
    assert success["content"]["*/*"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert set(success["headers"]) == {
        "Content-Disposition",
        "Content-Length",
        "Repr-Digest",
    }

    for status in ("401", "403", "404", "409", "503"):
        content = operation["responses"][status]["content"]
        schema = content["application/json"]["schema"]
        assert schema["$ref"] == "#/components/schemas/GeneralError"
