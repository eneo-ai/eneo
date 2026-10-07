import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest

from eneo.authentication import signed_urls
from eneo.authentication.signed_urls import (
    FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
    FILE_PROCESSING_DOWNLOAD_AUDIENCE,
    INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE,
    MAX_FUTURE_ISSUANCE_SECONDS,
    SIGNING_KEY,
    TOKEN_VERSION,
    generate_file_original_download_token,
    generate_info_blob_original_download_token,
    generate_signed_token,
    verify_file_original_download_token,
    verify_info_blob_original_download_token,
    verify_signed_token,
)
from eneo.files.file_models import (
    FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    ContentDisposition,
)

GENERATORS = {
    "processing": (
        generate_signed_token,
        verify_signed_token,
        FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        "file_id",
    ),
    "file_original": (
        generate_file_original_download_token,
        verify_file_original_download_token,
        FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        "file_id",
    ),
    "info_blob_original": (
        generate_info_blob_original_download_token,
        verify_info_blob_original_download_token,
        FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        "info_blob_id",
    ),
}


def _sign(payload: dict, key: bytes) -> str:
    message = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(key, message.encode(), hashlib.sha256).digest()
    ).decode()
    return f"{message}.{signature}"


def _mint(purpose: str, **overrides):
    generate, _, maximum, _ = GENERATORS[purpose]
    now = int(time.time())
    kwargs = {
        "expires_at": now + 60,
        "content_disposition": ContentDisposition.ATTACHMENT,
        "tenant_id": uuid4(),
        "issued_at": now,
    }
    kwargs.update(overrides)
    return generate(uuid4(), **kwargs)


@pytest.mark.parametrize("purpose", list(GENERATORS))
def test_tokens_carry_every_required_claim(purpose: str):
    generate, verify, _, resource_claim = GENERATORS[purpose]
    resource_id, tenant_id = uuid4(), uuid4()
    now = int(time.time())

    token = generate(
        resource_id,
        expires_at=now + 60,
        content_disposition=ContentDisposition.INLINE,
        tenant_id=tenant_id,
        issued_at=now,
    )

    payload = verify(token)
    assert payload is not None
    assert payload["v"] == TOKEN_VERSION
    assert payload[resource_claim] == str(resource_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["issued_at"] == now
    assert payload["expires_at"] == now + 60
    assert payload["content_disposition"] == "inline"


def test_each_purpose_has_its_own_audience_and_key():
    processing = _mint("processing")
    original = _mint("file_original")
    blob = _mint("info_blob_original")

    assert verify_signed_token(processing)["aud"] == FILE_PROCESSING_DOWNLOAD_AUDIENCE
    assert (
        verify_file_original_download_token(original)["aud"]
        == FILE_ORIGINAL_DOWNLOAD_AUDIENCE
    )
    assert (
        verify_info_blob_original_download_token(blob)["aud"]
        == INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE
    )
    # No token is accepted by another purpose's verifier.
    assert verify_file_original_download_token(processing) is None
    assert verify_info_blob_original_download_token(processing) is None
    assert verify_signed_token(original) is None
    assert verify_info_blob_original_download_token(original) is None
    assert verify_signed_token(blob) is None
    assert verify_file_original_download_token(blob) is None


def test_legacy_tokens_are_rejected_without_a_grace_period():
    """Tokens from the previous contract lack the version, issuance and
    audience claims and were signed with the raw key or the v1 purpose keys."""
    file_id, now = uuid4(), int(time.time())
    legacy_processing = _sign(
        {
            "file_id": str(file_id),
            "expires_at": now + 60,
            "content_disposition": "attachment",
        },
        SIGNING_KEY,
    )
    legacy_processing_with_tenant = _sign(
        {
            "file_id": str(file_id),
            "expires_at": now + 60,
            "content_disposition": "attachment",
            "tenant_id": str(uuid4()),
        },
        SIGNING_KEY,
    )
    legacy_original = _sign(
        {
            "file_id": str(file_id),
            "expires_at": now + 60,
            "content_disposition": "attachment",
            "aud": FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
            "tenant_id": str(uuid4()),
        },
        hmac.new(
            SIGNING_KEY, b"eneo:file-original-download:v1", hashlib.sha256
        ).digest(),
    )

    assert verify_signed_token(legacy_processing) is None
    assert verify_signed_token(legacy_processing_with_tenant) is None
    assert verify_file_original_download_token(legacy_original) is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"v": 1},
        {"v": "2"},
        {"aud": "something_else"},
        {"file_id": "not-a-uuid"},
        {"tenant_id": None},
        {"tenant_id": "not-a-uuid"},
        {"content_disposition": "download"},
        {"issued_at": "0"},
        {"issued_at": True},
        {"expires_at": 1.5},
    ],
)
def test_malformed_claims_are_rejected(mutation: dict, monkeypatch):
    """A token signed with the right key still fails when a claim is missing
    or of the wrong type; the signature alone proves nothing about lifetime."""
    now = int(time.time())
    payload = {
        "v": TOKEN_VERSION,
        "aud": FILE_PROCESSING_DOWNLOAD_AUDIENCE,
        "file_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "issued_at": now,
        "expires_at": now + 60,
        "content_disposition": "attachment",
    }
    payload.update(mutation)
    if mutation.get("tenant_id", "x") is None:
        del payload["tenant_id"]

    token = _sign(payload, signed_urls._FILE_PROCESSING_DOWNLOAD_KEY)
    assert verify_signed_token(token) is None


def test_tampered_signature_and_shape_are_rejected():
    token = _mint("file_original")
    message, signature = token.split(".")

    assert verify_file_original_download_token(f"{message}x.{signature}") is None
    assert verify_file_original_download_token(f"{message}.{signature}x") is None
    assert verify_file_original_download_token(message) is None
    assert verify_file_original_download_token("") is None
    assert verify_file_original_download_token("a.b.c") is None


@pytest.mark.parametrize("purpose", list(GENERATORS))
def test_expired_tokens_are_rejected_and_the_boundary_is_accepted(purpose: str):
    _, verify, _, _ = GENERATORS[purpose]
    now = int(time.time())

    assert verify(_mint(purpose, issued_at=now - 120, expires_at=now - 1)) is None
    assert verify(_mint(purpose, issued_at=now - 60, expires_at=now)) is not None


@pytest.mark.parametrize("purpose", list(GENERATORS))
def test_lifetime_may_not_exceed_the_purpose_maximum(purpose: str):
    generate, verify, maximum, _ = GENERATORS[purpose]
    now = int(time.time())

    # The generator refuses to mint beyond the maximum.
    with pytest.raises(ValueError, match="may not live longer"):
        _mint(purpose, issued_at=now, expires_at=now + maximum + 1)
    with pytest.raises(ValueError, match="must expire after"):
        _mint(purpose, issued_at=now, expires_at=now)

    # Exactly the maximum is a valid boundary.
    assert verify(_mint(purpose, issued_at=now, expires_at=now + maximum)) is not None

    # A token that claims a longer lifetime is rejected even with a valid
    # signature, so a compromised mint path cannot widen the window.
    key = {
        "processing": signed_urls._FILE_PROCESSING_DOWNLOAD_KEY,
        "file_original": signed_urls._FILE_ORIGINAL_DOWNLOAD_KEY,
        "info_blob_original": signed_urls._INFO_BLOB_ORIGINAL_DOWNLOAD_KEY,
    }[purpose]
    resource_claim = GENERATORS[purpose][3]
    audience = {
        "processing": FILE_PROCESSING_DOWNLOAD_AUDIENCE,
        "file_original": FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
        "info_blob_original": INFO_BLOB_ORIGINAL_DOWNLOAD_AUDIENCE,
    }[purpose]
    over_long = _sign(
        {
            "v": TOKEN_VERSION,
            "aud": audience,
            resource_claim: str(uuid4()),
            "tenant_id": str(uuid4()),
            "issued_at": now,
            "expires_at": now + maximum + 1,
            "content_disposition": "attachment",
        },
        key,
    )
    assert verify(over_long) is None


def test_future_issuance_is_limited_to_clock_skew():
    now = int(time.time())

    within_skew = _mint(
        "processing",
        issued_at=now + MAX_FUTURE_ISSUANCE_SECONDS - 5,
        expires_at=now + MAX_FUTURE_ISSUANCE_SECONDS + 55,
    )
    assert verify_signed_token(within_skew) is not None

    beyond_skew = _mint(
        "processing",
        issued_at=now + MAX_FUTURE_ISSUANCE_SECONDS + 5,
        expires_at=now + MAX_FUTURE_ISSUANCE_SECONDS + 65,
    )
    assert verify_signed_token(beyond_skew) is None


def test_issuance_must_precede_expiry_even_when_signed():
    now = int(time.time())
    token = _sign(
        {
            "v": TOKEN_VERSION,
            "aud": FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
            "file_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "issued_at": now + 30,
            "expires_at": now + 10,
            "content_disposition": "attachment",
        },
        signed_urls._FILE_ORIGINAL_DOWNLOAD_KEY,
    )
    assert verify_file_original_download_token(token) is None


def test_info_blob_original_token_cannot_be_replayed_as_file_token():
    info_blob_id, tenant_id, now = uuid4(), uuid4(), int(time.time())
    token = generate_info_blob_original_download_token(
        info_blob_id=info_blob_id,
        expires_at=now + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
        tenant_id=tenant_id,
        issued_at=now,
    )

    payload = verify_info_blob_original_download_token(token)
    assert payload is not None
    assert payload["info_blob_id"] == str(info_blob_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert verify_file_original_download_token(token) is None

    file_token = generate_file_original_download_token(
        file_id=info_blob_id,
        expires_at=now + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
        tenant_id=tenant_id,
        issued_at=now,
    )
    assert verify_info_blob_original_download_token(file_token) is None
