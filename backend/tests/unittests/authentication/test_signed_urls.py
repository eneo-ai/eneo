import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

from eneo.authentication.signed_urls import (
    FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
    SIGNING_KEY,
    generate_file_original_download_token,
    generate_signed_token,
    verify_file_original_download_token,
    verify_signed_token,
)
from eneo.files.file_models import ContentDisposition


def test_generate_signed_token_round_trips_tenant_scope() -> None:
    file_id = uuid4()
    tenant_id = uuid4()
    token = generate_signed_token(
        file_id=file_id,
        tenant_id=tenant_id,
        expires_at=4_102_444_800,
        content_disposition=ContentDisposition.ATTACHMENT,
    )

    payload = verify_signed_token(token)

    assert payload is not None
    assert payload["file_id"] == str(file_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["content_disposition"] == "attachment"


def test_verify_signed_token_rejects_file_or_tenant_mismatch() -> None:
    file_id = uuid4()
    tenant_id = uuid4()
    token = generate_signed_token(
        file_id=file_id,
        tenant_id=tenant_id,
        expires_at=4_102_444_800,
        content_disposition=ContentDisposition.INLINE,
    )

    assert (
        verify_signed_token(
            token,
            expected_file_id=uuid4(),
            expected_tenant_id=tenant_id,
        )
        is None
    )
    assert (
        verify_signed_token(
            token,
            expected_file_id=file_id,
            expected_tenant_id=uuid4(),
        )
        is None
    )


def test_original_download_token_uses_a_purpose_separated_signature():
    file_id = uuid4()
    tenant_id = uuid4()
    expires_at = int(time.time()) + 60
    token = generate_file_original_download_token(
        file_id=file_id,
        tenant_id=tenant_id,
        expires_at=expires_at,
        content_disposition=ContentDisposition.ATTACHMENT,
    )

    assert verify_file_original_download_token(token) == {
        "file_id": str(file_id),
        "tenant_id": str(tenant_id),
        "expires_at": expires_at,
        "content_disposition": "attachment",
        "aud": FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
    }
    assert verify_signed_token(token) is None


def test_legacy_processing_token_remains_audience_less():
    file_id = uuid4()
    tenant_id = uuid4()
    expires_at = int(time.time()) + 60

    token = generate_signed_token(
        file_id=file_id,
        tenant_id=tenant_id,
        expires_at=expires_at,
        content_disposition=ContentDisposition.INLINE,
    )

    assert verify_signed_token(token) == {
        "file_id": str(file_id),
        "tenant_id": str(tenant_id),
        "expires_at": expires_at,
        "content_disposition": "inline",
    }
    assert verify_file_original_download_token(token) is None

    expected_payload = {
        "file_id": str(file_id),
        "tenant_id": str(tenant_id),
        "expires_at": expires_at,
        "content_disposition": "inline",
    }
    message = base64.urlsafe_b64encode(json.dumps(expected_payload).encode()).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(SIGNING_KEY, message.encode(), hashlib.sha256).digest()
    ).decode()
    assert token == f"{message}.{signature}"


def test_tampered_and_expired_tokens_are_rejected():
    tenant_id = uuid4()
    token = generate_file_original_download_token(
        file_id=uuid4(),
        tenant_id=tenant_id,
        expires_at=int(time.time()) + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
    )
    message, signature = token.split(".")

    assert verify_file_original_download_token(f"{message}x.{signature}") is None
    assert (
        verify_file_original_download_token(
            generate_file_original_download_token(
                file_id=uuid4(),
                tenant_id=tenant_id,
                expires_at=int(time.time()) - 1,
                content_disposition=ContentDisposition.ATTACHMENT,
            )
        )
        is None
    )
