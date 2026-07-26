import base64
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

from eneo.files.file_models import (
    FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    ContentDisposition,
)
from eneo.main.config import get_settings


def _get_signing_key():
    """Get the signing key from settings."""
    return get_settings().url_signing_key.encode()


SIGNING_KEY = _get_signing_key()
FILE_ORIGINAL_DOWNLOAD_AUDIENCE = "file_original_download"
_FILE_ORIGINAL_DOWNLOAD_KEY = hmac.new(
    SIGNING_KEY,
    b"eneo:file-original-download:v1",
    hashlib.sha256,
).digest()


def _generate_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    *,
    signing_key: bytes,
    audience: str | None,
    tenant_id: UUID | None = None,
) -> str:
    payload: dict[str, Any] = {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": content_disposition.value,
    }
    if audience is not None:
        payload["aud"] = audience
    # tenant_id is covered by the HMAC, so the download handler can refuse
    # tokens whose signing-time tenant does not match the file being requested,
    # defending against cross-tenant replay if a URL leaks.
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)

    # Encode the payload as JSON and then base64
    message = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    # Create a signature using HMAC-SHA256
    signature = hmac.new(signing_key, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode()

    # Return the token in the format message.signature
    return f"{message}.{signature_b64}"


def generate_signed_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID | None = None,
) -> str:
    """Generate a legacy processing-download token."""
    return _generate_token(
        file_id,
        expires_at,
        content_disposition,
        signing_key=SIGNING_KEY,
        audience=None,
        tenant_id=tenant_id,
    )


def generate_file_original_download_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID | None = None,
) -> str:
    """Generate a token that is valid only for exact-original downloads."""
    return _generate_token(
        file_id,
        expires_at,
        content_disposition,
        signing_key=_FILE_ORIGINAL_DOWNLOAD_KEY,
        audience=FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
        tenant_id=tenant_id,
    )


def _verify_token(token: str, *, signing_key: bytes) -> dict[str, Any] | None:
    try:
        # Split the token into message and signature parts
        if "." not in token:
            return None

        message, signature_b64 = token.split(".")

        # Decode the signature
        try:
            signature = base64.urlsafe_b64decode(signature_b64)
        except Exception:
            return None

        # Compute the expected signature
        expected_signature = hmac.new(
            signing_key, message.encode(), hashlib.sha256
        ).digest()

        # Compare signatures using constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(signature, expected_signature):
            return None

        # Decode the payload
        try:
            payload_json = base64.urlsafe_b64decode(message).decode()
            payload = json.loads(payload_json)
        except Exception:
            return None

        # Check if the URL has expired
        if payload["expires_at"] < int(time.time()):
            return None

        return payload
    except Exception:
        return None


def verify_signed_token(token: str) -> dict[str, Any] | None:
    """Verify a legacy processing-download token."""
    return _verify_token(token, signing_key=SIGNING_KEY)


def verify_file_original_download_token(token: str) -> dict[str, Any] | None:
    """Verify an exact-original token using its purpose-separated key."""
    payload = _verify_token(token, signing_key=_FILE_ORIGINAL_DOWNLOAD_KEY)
    if payload is None or payload.get("aud") != FILE_ORIGINAL_DOWNLOAD_AUDIENCE:
        return None
    return payload


def build_signed_original_download_url(
    file_id: UUID,
    base_url: str,
    expires_in: int,
    tenant_id: UUID | None = None,
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT,
) -> str:
    """Build an absolute signed URL for an exact-original download.

    Used where there is no ``Request`` object (e.g. the completion layer minting
    file references for MCP tools), so ``base_url`` must be a configured origin
    (no trailing slash). ``expires_in`` is clamped to the original-download
    token maximum so a config value cannot extend a leaked URL's lifetime.
    """
    expires_in = min(expires_in, FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS)
    expires_at = int(time.time()) + expires_in
    token = generate_file_original_download_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=content_disposition,
        tenant_id=tenant_id,
    )
    return (
        f"{base_url.rstrip('/')}/api/v1/files/{file_id}/original/download/"
        f"?token={token}"
    )
