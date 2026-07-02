from __future__ import annotations

import time
from uuid import UUID

from eneo.authentication.signed_urls import generate_signed_token
from eneo.files.file_models import SignedURLRequest, SignedURLResponse

_SIGNED_FILE_DOWNLOAD_PATH_TEMPLATE = "/api/v1/files/{file_id}/download/"


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
    )
    url = (
        f"{base_url.rstrip('/')}"
        f"{_SIGNED_FILE_DOWNLOAD_PATH_TEMPLATE.format(file_id=file_id)}"
        f"?token={token}"
    )
    return SignedURLResponse(url=url, expires_at=expires_at)
