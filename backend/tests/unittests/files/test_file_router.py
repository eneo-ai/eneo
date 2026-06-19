from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.signed_urls import verify_signed_token
from intric.files import file_router
from intric.files.file_models import SignedURLRequest
from intric.main.exceptions import NotFoundException, UnauthorizedException


async def test_generate_signed_url_uses_file_tenant_for_token():
    file_id = uuid4()
    tenant_id = uuid4()
    file_service = SimpleNamespace(
        get_file_infos=AsyncMock(return_value=[SimpleNamespace(tenant_id=tenant_id)])
    )
    container = SimpleNamespace(file_service=lambda: file_service)

    response = await file_router.generate_signed_url(
        id=file_id,
        request=SimpleNamespace(base_url="https://app.example.com/"),
        signed_url_req=SignedURLRequest(expires_in=120),
        container=container,
    )

    file_service.get_file_infos.assert_awaited_once_with(file_ids=[file_id])
    assert response.url.startswith(
        f"https://app.example.com/api/v1/files/{file_id}/download/?token="
    )
    token = response.url.split("token=", 1)[1]
    payload = verify_signed_token(
        token,
        expected_file_id=file_id,
        expected_tenant_id=tenant_id,
    )
    assert payload is not None
    assert payload["expires_at"] == response.expires_at


async def test_download_file_signed_raises_not_found_for_missing_content(monkeypatch):
    file_id = uuid4()
    tenant_id = uuid4()
    payload = {
        "file_id": str(file_id),
        "tenant_id": str(tenant_id),
        "content_disposition": "inline",
    }

    def _verify(_token, **kwargs):
        if (
            kwargs.get("expected_file_id") is not None
            and str(kwargs["expected_file_id"]) != payload["file_id"]
        ):
            return None
        if (
            kwargs.get("expected_tenant_id") is not None
            and str(kwargs["expected_tenant_id"]) != payload["tenant_id"]
        ):
            return None
        return payload

    monkeypatch.setattr(file_router, "verify_signed_token", _verify)

    file_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(text=None, blob=None, tenant_id=tenant_id)
        )
    )
    container = SimpleNamespace(file_repo=lambda: file_repo)

    with pytest.raises(NotFoundException, match="File content not found"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=container
        )


async def test_download_file_signed_rejects_cross_tenant_token(monkeypatch):
    file_id = uuid4()
    payload = {
        "file_id": str(file_id),
        "tenant_id": str(uuid4()),
        "content_disposition": "inline",
    }

    def _verify(_token, **kwargs):
        if (
            kwargs.get("expected_file_id") is not None
            and str(kwargs["expected_file_id"]) != payload["file_id"]
        ):
            return None
        if (
            kwargs.get("expected_tenant_id") is not None
            and str(kwargs["expected_tenant_id"]) != payload["tenant_id"]
        ):
            return None
        return payload

    monkeypatch.setattr(file_router, "verify_signed_token", _verify)

    file_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                text="hello",
                blob=None,
                tenant_id=uuid4(),
                file_type="text",
                mimetype="text/plain",
                name="note.txt",
            )
        )
    )
    container = SimpleNamespace(file_repo=lambda: file_repo)

    with pytest.raises(UnauthorizedException, match="Token not valid for this tenant"):
        await file_router.download_file_signed(
            id=file_id, token="token", range=None, container=container
        )
