import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from eneo.files.file_models import (
    FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    ContentDisposition,
)
from eneo.main.config import get_settings


def _get_signing_key() -> bytes:
    """The configured signing key; its strength is validated at startup."""
    return get_settings().url_signing_key.encode("utf-8")


SIGNING_KEY = _get_signing_key()

# Token contract version. Every claim below is required; anything older is
# rejected outright because it cannot prove its lifetime or its tenant.
TOKEN_VERSION = 2

FILE_PROCESSING_DOWNLOAD_AUDIENCE = "file_processing_download"
FILE_ORIGINAL_DOWNLOAD_AUDIENCE = "file_original_download"
INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE = "info_blob_original_download"

# How far in the future ``issued_at`` may lie before the token is rejected;
# covers clock skew between replicas without admitting pre-dated tokens.
MAX_FUTURE_ISSUANCE_SECONDS = 60


def _derive_key(purpose: bytes) -> bytes:
    return hmac.new(SIGNING_KEY, purpose, hashlib.sha256).digest()


_FILE_PROCESSING_DOWNLOAD_KEY = _derive_key(b"eneo:file-processing-download:v2")
_FILE_ORIGINAL_DOWNLOAD_KEY = _derive_key(b"eneo:file-original-download:v2")
_INFO_BLOB_ORIGINAL_DOWNLOAD_KEY = _derive_key(b"eneo:info-blob-original-download:v2")


def _generate_token(
    resource_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    *,
    signing_key: bytes,
    audience: str,
    tenant_id: UUID,
    resource_claim: str,
    maximum_lifetime_seconds: int,
    issued_at: int | None = None,
) -> str:
    """Sign a version-2 download token.

    The lifetime is checked here as well as at the API boundary so no caller
    can mint a link that outlives its purpose's maximum.
    """
    issued_at = int(time.time()) if issued_at is None else issued_at
    lifetime = expires_at - issued_at
    if lifetime <= 0:
        raise ValueError("A signed download token must expire after it is issued")
    if lifetime > maximum_lifetime_seconds:
        raise ValueError(
            "A signed download token may not live longer than "
            f"{maximum_lifetime_seconds} seconds"
        )

    payload: dict[str, Any] = {
        "v": TOKEN_VERSION,
        "aud": audience,
        resource_claim: str(resource_id),
        # Bind the credential to the tenant that owns the resource, so a
        # leaked link cannot be redeemed against another tenant's copy.
        "tenant_id": str(tenant_id),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "content_disposition": content_disposition.value,
    }
    message = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(signing_key, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode()
    return f"{message}.{signature_b64}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_uuid_string(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _verify_token(
    token: str,
    *,
    signing_key: bytes,
    audience: str,
    resource_claim: str,
    maximum_lifetime_seconds: int,
) -> dict[str, Any] | None:
    """Verify signature, contract version, claim types and lifetime.

    Returns the payload only when every required claim is present and well
    formed, the audience matches the verifier's purpose, the token was issued
    before it expires, its lifetime is within the purpose's maximum, it has
    not expired, and it was not issued more than a short skew in the future.
    Anything else, including every token from the previous contract, is
    rejected.
    """
    try:
        message, signature_b64 = token.split(".")
        signature = base64.urlsafe_b64decode(signature_b64)
    except Exception:
        return None
    # Only the canonical encoding of a 32-byte digest is a signature; trailing
    # or substituted characters that decode to the same bytes are rejected.
    if (
        len(signature) != hashlib.sha256().digest_size
        or base64.urlsafe_b64encode(signature).decode() != signature_b64
    ):
        return None

    expected_signature = hmac.new(
        signing_key, message.encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(message).decode())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    claims = cast(dict[str, object], payload)

    if claims.get("v") != TOKEN_VERSION:
        return None
    if claims.get("aud") != audience:
        return None
    if not _is_uuid_string(claims.get(resource_claim)):
        return None
    if not _is_uuid_string(claims.get("tenant_id")):
        return None
    disposition = claims.get("content_disposition")
    if not isinstance(disposition, str) or disposition not in {
        item.value for item in ContentDisposition
    }:
        return None
    issued_at = claims.get("issued_at")
    expires_at = claims.get("expires_at")
    if not _is_int(issued_at) or not _is_int(expires_at):
        return None
    issued_at = cast(int, issued_at)
    expires_at = cast(int, expires_at)
    if issued_at >= expires_at:
        return None
    if expires_at - issued_at > maximum_lifetime_seconds:
        return None

    now = int(time.time())
    if expires_at < now:
        return None
    if issued_at > now + MAX_FUTURE_ISSUANCE_SECONDS:
        return None

    return cast(dict[str, Any], claims)


def generate_signed_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID,
    *,
    issued_at: int | None = None,
) -> str:
    """Generate a processing-download token (extracted or derived content)."""
    return _generate_token(
        file_id,
        expires_at,
        content_disposition,
        signing_key=_FILE_PROCESSING_DOWNLOAD_KEY,
        audience=FILE_PROCESSING_DOWNLOAD_AUDIENCE,
        tenant_id=tenant_id,
        resource_claim="file_id",
        maximum_lifetime_seconds=FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        issued_at=issued_at,
    )


def generate_file_original_download_token(
    file_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID,
    *,
    issued_at: int | None = None,
) -> str:
    """Generate a token that is valid only for exact-original downloads."""
    return _generate_token(
        file_id,
        expires_at,
        content_disposition,
        signing_key=_FILE_ORIGINAL_DOWNLOAD_KEY,
        audience=FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
        tenant_id=tenant_id,
        resource_claim="file_id",
        maximum_lifetime_seconds=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        issued_at=issued_at,
    )


def generate_info_blob_original_download_token(
    info_blob_id: UUID,
    expires_at: int,
    content_disposition: ContentDisposition,
    tenant_id: UUID,
    *,
    issued_at: int | None = None,
) -> str:
    """Generate a purpose-separated token for an InfoBlob original."""
    return _generate_token(
        info_blob_id,
        expires_at,
        content_disposition,
        signing_key=_INFO_BLOB_ORIGINAL_DOWNLOAD_KEY,
        audience=INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE,
        tenant_id=tenant_id,
        resource_claim="info_blob_id",
        maximum_lifetime_seconds=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        issued_at=issued_at,
    )


def verify_signed_token(token: str) -> dict[str, Any] | None:
    """Verify a processing-download token."""
    return _verify_token(
        token,
        signing_key=_FILE_PROCESSING_DOWNLOAD_KEY,
        audience=FILE_PROCESSING_DOWNLOAD_AUDIENCE,
        resource_claim="file_id",
        maximum_lifetime_seconds=FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


def verify_file_original_download_token(token: str) -> dict[str, Any] | None:
    """Verify an exact-original token using its purpose-separated key."""
    return _verify_token(
        token,
        signing_key=_FILE_ORIGINAL_DOWNLOAD_KEY,
        audience=FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
        resource_claim="file_id",
        maximum_lifetime_seconds=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


def verify_info_blob_original_download_token(token: str) -> dict[str, Any] | None:
    """Verify an InfoBlob original token and its explicit audience."""
    return _verify_token(
        token,
        signing_key=_INFO_BLOB_ORIGINAL_DOWNLOAD_KEY,
        audience=INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE,
        resource_claim="info_blob_id",
        maximum_lifetime_seconds=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


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


_REFERENCE_TOKEN = re.compile(
    r"(?P<prefix>/original/download/?\?(?:[^\s\"'<>]*?&)?token=)"
    r"[A-Za-z0-9_\-=.]+"
)
REDACTED_TOKEN = "REDACTED"


def redact_reference_tokens(value: object) -> object:
    """Replace the signed token in every reference URL found in ``value``.

    Strings are scanned for original-download links; dicts and lists are
    walked; other values pass through untouched. Applied to tool-call
    arguments and results before they are persisted or shown, so the
    bearer credential lives only in the request that used it. The URL keeps
    its shape (a placeholder token remains) so later readers can still tell
    a reference apart from a web link.
    """
    if isinstance(value, str):
        return _REFERENCE_TOKEN.sub(rf"\g<prefix>{REDACTED_TOKEN}", value)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {key: redact_reference_tokens(item) for key, item in mapping.items()}
    if isinstance(value, list):
        entries = cast(list[object], value)
        return [redact_reference_tokens(item) for item in entries]
    return value


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
    tenant_id: UUID,
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT,
) -> str:
    """Build an absolute signed URL for an exact-original download.

    Used where there is no ``Request`` object (e.g. the completion layer minting
    file references for MCP tools), so ``base_url`` must be a configured origin
    (no trailing slash). ``expires_in`` is clamped to the original-download
    token maximum so a config value cannot extend a leaked URL's lifetime.
    """
    expires_in = max(
        1, min(expires_in, FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS)
    )
    issued_at = int(time.time())
    token = generate_file_original_download_token(
        file_id=file_id,
        expires_at=issued_at + expires_in,
        content_disposition=content_disposition,
        tenant_id=tenant_id,
        issued_at=issued_at,
    )
    return (
        f"{base_url.rstrip('/')}/api/v1/files/{file_id}/original/download/"
        f"?token={token}"
    )
