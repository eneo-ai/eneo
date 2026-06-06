import base64
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

from eneo.files.file_models import ContentDisposition
from eneo.main.config import get_settings


def _get_signing_key():
    """Get the signing key from settings."""
    return get_settings().url_signing_key.encode()


SIGNING_KEY = _get_signing_key()


def generate_signed_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID | None = None,
    variant: str = "text",
) -> str:
    """Generate a signed token for file access.

    ``tenant_id`` is encoded in the payload (and therefore covered by the HMAC)
    so the download handler can refuse tokens whose tenant does not match the
    file being requested, defending against cross-tenant replay if a URL leaks.

    ``variant`` selects what the download serves: ``"text"`` (the extracted
    ``.txt``, the historical behavior) or ``"original"`` (the original upload
    bytes streamed from external storage). Because it is inside the signed
    payload, a ``"text"`` URL cannot be tampered into fetching the original.
    """
    payload = {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": content_disposition.value,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "variant": variant,
    }

    # Encode the payload as JSON and then base64
    message = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    # Create a signature using HMAC-SHA256
    signature = hmac.new(SIGNING_KEY, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode()

    # Return the token in the format message.signature
    return f"{message}.{signature_b64}"


def verify_signed_token(token: str) -> dict[str, Any] | None:
    """Verify a signed token and return the payload if valid."""
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
            SIGNING_KEY, message.encode(), hashlib.sha256
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


def build_signed_download_url(
    file_id: UUID,
    base_url: str,
    expires_in: int,
    tenant_id: UUID | None = None,
    variant: str = "original",
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT,
) -> str:
    """Build an absolute signed download URL for a file.

    Used where there is no ``Request`` object (e.g. the completion layer), so
    ``base_url`` must be the configured public origin (no trailing slash).
    """
    expires_at = int(time.time()) + expires_in
    token = generate_signed_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=content_disposition,
        tenant_id=tenant_id,
        variant=variant,
    )
    return f"{base_url.rstrip('/')}/api/v1/files/{file_id}/download/?token={token}"
