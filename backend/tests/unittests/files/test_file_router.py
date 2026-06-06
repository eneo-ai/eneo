from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.responses import StreamingResponse

from eneo.files import file_router
from eneo.main.exceptions import NotFoundException, UnauthorizedException


async def test_download_file_signed_raises_not_found_for_missing_content(monkeypatch):
    file_id = uuid4()
    tenant_id = uuid4()
    # tenant_id must be present and match the file (cross-tenant replay guard);
    # variant omitted so the original-bytes branch is skipped.
    payload = {
        "file_id": str(file_id),
        "content_disposition": "inline",
        "tenant_id": str(tenant_id),
    }

    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    file_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                text=None, blob=None, tenant_id=tenant_id, storage_key=None
            )
        )
    )
    object_storage = SimpleNamespace(is_configured=lambda: False)
    container = SimpleNamespace(
        file_repo=lambda: file_repo,
        file_object_storage=lambda: object_storage,
    )

    with pytest.raises(NotFoundException, match="File content not found"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=container
        )


async def test_download_file_signed_rejects_cross_tenant_token(monkeypatch):
    file_id = uuid4()
    payload = {
        "file_id": str(file_id),
        "content_disposition": "inline",
        "tenant_id": str(uuid4()),  # different from the file's tenant
    }
    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    file_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                text="x", blob=None, tenant_id=uuid4(), storage_key=None
            )
        )
    )
    container = SimpleNamespace(file_repo=lambda: file_repo)

    with pytest.raises(UnauthorizedException):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=container
        )


async def test_download_file_signed_streams_original_from_storage(monkeypatch):
    file_id = uuid4()
    tenant_id = uuid4()
    payload = {
        "file_id": str(file_id),
        "content_disposition": "attachment",
        "tenant_id": str(tenant_id),
        "variant": "original",
    }
    monkeypatch.setattr(file_router, "verify_signed_token", lambda _: payload)

    file = SimpleNamespace(
        text="extracted",
        blob=None,
        tenant_id=tenant_id,
        storage_key="tenant/uuid/doc.pdf",
        mimetype="application/pdf",
        name="doc.pdf",
    )
    file_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=file))

    async def fake_stream(_key):
        yield b"%PDF-1.7"

    object_storage = SimpleNamespace(
        is_configured=lambda: True, open_stream=fake_stream
    )
    container = SimpleNamespace(
        file_repo=lambda: file_repo,
        file_object_storage=lambda: object_storage,
    )

    response = await file_router.download_file_signed(
        id=file_id, token="token", range=None, container=container
    )

    # Original bytes are served with the original mimetype, not as .txt.
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "application/pdf"
