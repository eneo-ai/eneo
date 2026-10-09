"""A document template link is signed for one template of one tenant, and its
token is redacted like a file reference without being taken for one."""

from uuid import uuid4

from eneo.authentication.signed_urls import (
    build_signed_document_template_url,
    parse_file_reference_url,
    redact_reference_tokens,
    redact_reference_tokens_in_json,
    reference_file_ids,
    verify_document_template_download_token,
    verify_file_original_download_token,
)


def test_template_link_round_trips_and_is_purpose_separated():
    template_id, tenant_id = uuid4(), uuid4()
    url = build_signed_document_template_url(
        template_id,
        base_url="https://eneo.example/",
        expires_in=600,
        tenant_id=tenant_id,
    )
    assert url.startswith(
        f"https://eneo.example/api/v1/document-templates/{template_id}/original/download/?token="
    )
    token = url.split("token=")[1]
    payload = verify_document_template_download_token(token)
    assert payload is not None
    assert payload["template_id"] == str(template_id)
    assert payload["tenant_id"] == str(tenant_id)
    # A template token opens no file, and a file token opens no template.
    assert verify_file_original_download_token(token) is None


def test_template_link_is_redacted_but_is_not_a_conversation_file():
    url = build_signed_document_template_url(
        uuid4(), base_url="https://eneo.example", expires_in=600, tenant_id=uuid4()
    )
    arguments = {"template": {"url": url, "filename": "mall.docx"}}
    redacted = redact_reference_tokens(arguments)
    assert redacted["template"]["url"].endswith("token=REDACTED")
    assert "token=REDACTED" in redact_reference_tokens_in_json(f'{{"url": "{url}"}}')
    assert reference_file_ids(arguments, include_redacted=True) == set()
    assert parse_file_reference_url(url) is None
