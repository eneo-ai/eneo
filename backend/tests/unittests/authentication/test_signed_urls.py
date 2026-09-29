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
    generate_info_blob_original_download_token,
    generate_signed_token,
    verify_file_original_download_token,
    verify_info_blob_original_download_token,
    verify_signed_token,
)
from eneo.files.file_models import ContentDisposition


def test_original_download_token_uses_a_purpose_separated_signature():
    file_id = uuid4()
    expires_at = int(time.time()) + 60
    token = generate_file_original_download_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=ContentDisposition.ATTACHMENT,
    )
    assert verify_file_original_download_token(token) == {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": "attachment",
        "aud": FILE_ORIGINAL_DOWNLOAD_AUDIENCE,
    }
    assert verify_signed_token(token) is None


def test_legacy_processing_token_remains_audience_less():
    file_id = uuid4()
    expires_at = int(time.time()) + 60

    token = generate_signed_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=ContentDisposition.INLINE,
    )

    assert verify_signed_token(token) == {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": "inline",
    }
    assert verify_file_original_download_token(token) is None

    expected_payload = {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": "inline",
    }
    message = base64.urlsafe_b64encode(json.dumps(expected_payload).encode()).decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(SIGNING_KEY, message.encode(), hashlib.sha256).digest()
    ).decode()
    assert token == f"{message}.{signature}"


def test_tampered_and_expired_tokens_are_rejected():
    token = generate_file_original_download_token(
        file_id=uuid4(),
        expires_at=int(time.time()) + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
    )
    message, signature = token.split(".")

    assert verify_file_original_download_token(f"{message}x.{signature}") is None
    assert (
        verify_file_original_download_token(
            generate_file_original_download_token(
                file_id=uuid4(),
                expires_at=int(time.time()) - 1,
                content_disposition=ContentDisposition.ATTACHMENT,
            )
        )
        is None
    )


def test_info_blob_original_token_cannot_be_replayed_as_file_token():
    info_blob_id = uuid4()
    tenant_id = uuid4()
    token = generate_info_blob_original_download_token(
        info_blob_id=info_blob_id,
        expires_at=int(time.time()) + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
        tenant_id=tenant_id,
    )

    payload = verify_info_blob_original_download_token(token)
    assert payload is not None
    assert payload["info_blob_id"] == str(info_blob_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["content_disposition"] == "attachment"
    assert verify_file_original_download_token(token) is None

    file_token = generate_file_original_download_token(
        file_id=info_blob_id,
        expires_at=int(time.time()) + 60,
        content_disposition=ContentDisposition.ATTACHMENT,
        tenant_id=tenant_id,
    )
    assert verify_info_blob_original_download_token(file_token) is None
