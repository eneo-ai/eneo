from uuid import uuid4

from intric.authentication.signed_urls import generate_signed_token, verify_signed_token
from intric.files.file_models import ContentDisposition


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
