import time
from uuid import uuid4

from intric.authentication.signed_urls import verify_signed_token
from intric.files.file_models import ContentDisposition, SignedURLRequest
from intric.files.signed_urls import build_signed_download_response


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
