"""MCP App view tokens are purpose-separated HMAC tokens: they round-trip
with their tenant claim, expire, and are rejected across purposes (a file
token never authorizes a view and vice versa)."""

import time
from uuid import uuid4

from eneo.authentication.signed_urls import (
    generate_file_original_download_token,
    generate_mcp_app_view_token,
    verify_file_original_download_token,
    verify_mcp_app_view_token,
)
from eneo.files.file_models import ContentDisposition


def test_roundtrip_carries_view_and_tenant_claims():
    view_id, tenant_id = uuid4(), uuid4()
    expires_at = int(time.time()) + 60

    token = generate_mcp_app_view_token(
        view_id=view_id, tenant_id=tenant_id, expires_at=expires_at
    )
    payload = verify_mcp_app_view_token(token)

    assert payload is not None
    assert payload["view_id"] == str(view_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["expires_at"] == expires_at


def test_expired_token_is_rejected():
    now = int(time.time())
    token = generate_mcp_app_view_token(
        view_id=uuid4(), tenant_id=uuid4(), expires_at=now - 1, issued_at=now - 120
    )

    assert verify_mcp_app_view_token(token) is None


def test_tampered_token_is_rejected():
    token = generate_mcp_app_view_token(
        view_id=uuid4(), tenant_id=uuid4(), expires_at=int(time.time()) + 60
    )
    message, signature = token.split(".")
    tampered = message[:-2] + "xx" + "." + signature

    assert verify_mcp_app_view_token(tampered) is None


def test_cross_purpose_tokens_are_rejected_both_ways():
    expires_at = int(time.time()) + 60
    file_token = generate_file_original_download_token(
        file_id=uuid4(),
        expires_at=expires_at,
        content_disposition=ContentDisposition.ATTACHMENT,
        tenant_id=uuid4(),
    )
    view_token = generate_mcp_app_view_token(
        view_id=uuid4(), tenant_id=uuid4(), expires_at=expires_at
    )

    assert verify_mcp_app_view_token(file_token) is None
    assert verify_file_original_download_token(view_token) is None
