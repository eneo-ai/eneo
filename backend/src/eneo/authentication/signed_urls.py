import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
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


# Path suffix of a signed original-download URL (the shape minted by
# build_signed_original_download_url); matched host-agnostically because the
# HMAC token is the sole authorizer.
_FILE_ORIGINAL_DOWNLOAD_PATH = re.compile(
    r"/api/v1/files/(?P<file_id>[0-9a-fA-F-]{36})/original/download/?$"
)


def parse_file_reference_url(url: str) -> tuple[UUID, str] | None:
    """Extract ``(file_id, token)`` from a signed original-download URL.

    Host-agnostic on purpose: the signed token is the sole authorizer, so
    links minted against either the public origin or the tool-facing
    reference base URL both resolve. The inverse of
    :func:`build_signed_original_download_url`; the token is not verified
    here.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    match = _FILE_ORIGINAL_DOWNLOAD_PATH.search(parts.path)
    if match is None:
        return None
    tokens = parse_qs(parts.query).get("token")
    if not tokens or not tokens[0]:
        return None
    try:
        file_id = UUID(match.group("file_id"))
    except ValueError:
        return None
    return file_id, tokens[0]


def looks_like_reference_url(url: str) -> bool:
    """Whether ``url`` has the shape of a signed attachment reference.

    Shape only, no verification: lets infrastructure recognize a reference in
    tool arguments (e.g. to hint at the built-in reader when an external tool
    fails) without authorizing anything.
    """
    return parse_file_reference_url(url) is not None


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
