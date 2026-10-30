import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.authentication.signed_urls import verify_signed_token
from eneo.files.file_models import ContentDisposition, SignedURLRequest
from eneo.files.signed_urls import build_signed_download_response


@pytest.mark.parametrize("expires_in", [0, -1, 86401])
def test_signed_url_request_rejects_expiry_outside_supported_range(
    expires_in: int,
) -> None:
    with pytest.raises(ValidationError):
        SignedURLRequest(expires_in=expires_in)


@pytest.mark.parametrize("expires_in", [3660, 86400])
def test_signed_url_request_accepts_supported_expiry(expires_in: int) -> None:
    assert SignedURLRequest(expires_in=expires_in).expires_in == expires_in


def test_signed_url_request_defaults_expiry_to_one_hour() -> None:
    assert SignedURLRequest().expires_in == 3600


def test_build_signed_download_response_preserves_tenant_bound_token() -> None:
    file_id = uuid4()
    tenant_id = uuid4()
    now = int(time.time())

    response = build_signed_download_response(
        base_url="https://app.example.com/",
        file_id=file_id,
        tenant_id=tenant_id,
        signed_url_request=SignedURLRequest(
            expires_in=300,
            content_disposition=ContentDisposition.INLINE,
        ),
        now=now,
    )

    assert response.expires_at == now + 300
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
    assert payload["file_id"] == str(file_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["expires_at"] == now + 300
    assert payload["content_disposition"] == ContentDisposition.INLINE.value


def test_build_signed_download_response_respects_epoch_zero_now() -> None:
    response = build_signed_download_response(
        base_url="https://app.example.com",
        file_id=uuid4(),
        tenant_id=uuid4(),
        signed_url_request=SignedURLRequest(expires_in=60),
        now=0,
    )

    assert response.expires_at == 60


def test_build_signed_download_response_rejects_cross_tenant_round_trip() -> None:
    response = build_signed_download_response(
        base_url="https://app.example.com",
        file_id=uuid4(),
        tenant_id=uuid4(),
        signed_url_request=SignedURLRequest(expires_in=60),
    )

    token = response.url.split("token=", 1)[1]

    assert verify_signed_token(token, expected_tenant_id=uuid4()) is None
