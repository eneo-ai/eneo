from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.authentication.signed_urls import generate_signed_token
from eneo.files.file_models import SignedURLRequest, SignedURLResponse
from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.tenants.tenant import TenantInDB


def public_api_origin(tenant: TenantInDB) -> str | None:
    """The origin a client outside Eneo reaches the API on, or None when none
    is configured: the tenant's canonical public origin, else PUBLIC_ORIGIN.

    Never the file reference base URL, which may be an internal address that
    only a tool next to the backend can reach."""
    origin = tenant.federation_config.get("canonical_public_origin")
    if isinstance(origin, str) and origin.strip():
        return origin.strip()
    return get_settings().public_origin or None


def build_signed_download_response(
    *,
    base_url: str,
    file_id: UUID,
    tenant_id: UUID,
    signed_url_request: SignedURLRequest,
    now: int | None = None,
) -> SignedURLResponse:
    issued_at = now if now is not None else int(time.time())
    expires_at = issued_at + signed_url_request.expires_in
    token = generate_signed_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=signed_url_request.content_disposition,
        tenant_id=tenant_id,
        issued_at=issued_at,
    )
    url = (
        f"{base_url.rstrip('/')}{get_settings().api_prefix}"
        f"/files/{file_id}/download/?token={token}"
    )
    return SignedURLResponse(url=url, expires_at=expires_at)
