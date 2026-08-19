from __future__ import annotations

from urllib.parse import unquote

import pytest

from eneo.flows.application.flow_webhook_delivery_policy import (
    sanitize_webhook_delivery_error,
)
from eneo.flows.flow_run_redaction import (
    MaskedField,
    StringRedactionResult,
    is_sensitive_key,
    redact_payload,
    redact_payload_with_manifest,
    redact_string,
    redact_string_with_reason,
    redact_url_secrets,
)


def test_redact_payload_redacts_nested_sensitive_fields_and_bearer_tokens():
    payload = {
        "headers": {
            "Authorization": "Bearer super-secret-token",
            "X-Api-Key": "abc123",
        },
        "message": "Bearer another-secret",
        "nested": [{"session_cookie": "cookie-value"}],
    }

    redacted = redact_payload(payload)

    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["headers"]["X-Api-Key"] == "[REDACTED]"
    assert redacted["message"] == "Bearer [REDACTED]"
    assert redacted["nested"][0]["session_cookie"] == "[REDACTED]"


def test_redact_url_secrets_removes_credentials_and_sensitive_query_values():
    value = (
        "https://user:pass@example.com/path?code=auth-code&state=csrf-state"
        "&token_hint=token-value&secret_label=secret-value&safe=yes"
    )

    redacted = redact_url_secrets(value)

    assert "user:pass" not in redacted
    assert "auth-code" not in redacted
    assert "csrf-state" not in redacted
    assert "token-value" not in redacted
    assert "secret-value" not in redacted
    assert "safe=yes" in redacted


def test_redact_string_redacts_sensitive_assignments_in_diagnostics() -> None:
    cases = (
        ("request failed password=alpha123", ("alpha123",)),
        ("request failed password=left,right;tail", ("left", "right", "tail")),
        ("request failed api_key=beta456", ("beta456",)),
        ("params={'password': 'gamma789'}", ("gamma789",)),
        ('payload={"client_secret": "delta012"}', ("delta012",)),
        ("headers Authorization: Basic dXNlcjpwYXNz", ("dXNlcjpwYXNz",)),
    )

    for value, secrets in cases:
        redacted = redact_string(value, key="message")

        assert "[REDACTED]" in redacted
        for secret in secrets:
            assert secret not in redacted

    assert (
        redact_string(
            "POST https://example.com/audit?token=top-secret failed",
            key="message",
        )
        == "POST https://example.com/audit?token=%5BREDACTED%5D failed"
    )


def test_redact_string_redacts_url_secrets_embedded_in_prose() -> None:
    value = (
        "Request failed for "
        "https://user:pass@example.com/hook?access_token=secret-value&safe=yes; "
        "retry later."
    )

    redacted = redact_string(value, key="message")

    assert "user:pass" not in redacted
    assert "secret-value" not in redacted
    assert "https://example.com/hook?access_token=%5BREDACTED%5D&safe=yes" in redacted
    assert redacted.endswith("; retry later.")


def test_redact_string_redacts_standalone_authorization_credentials() -> None:
    cases = (
        ("Basic dXNlcjpwYXNz", "Basic"),
        ("Bearer bearer-token-value", "Bearer"),
        ('Digest username="operator", response="digest-secret"', "Digest"),
    )
    for credential, scheme in cases:
        redacted = redact_string(
            f"Audit delivery failed with {credential}",
            key="message",
        )

        assert redacted == f"Audit delivery failed with {scheme} [REDACTED]"


def test_redact_payload_matches_camel_case_sensitive_keys() -> None:
    payload = {
        "clientSecret": "client-secret-value",
        "accessToken": "access-token-value",
        "passwordHash": "password-hash-value",
    }

    assert redact_payload(payload) == {
        "clientSecret": "[REDACTED]",
        "accessToken": "[REDACTED]",
        "passwordHash": "[REDACTED]",
    }


def test_redact_url_secrets_redacts_short_signature_parameter() -> None:
    redacted = redact_url_secrets(
        "https://storage.example/object?sig=signature-value&request_id=case-1"
    )

    assert "signature-value" not in redacted
    assert "sig=%5BREDACTED%5D" in redacted
    assert "request_id=case-1" in redacted


def test_redact_string_redacts_secrets_in_nested_url_query_values() -> None:
    value = (
        "Request failed for https://gateway.example/hook?"
        "redirect=https://user:pass@receiver.example/cb?token=secret-value"
        "&request_id=case-123"
    )

    redacted = redact_string(value, key="message")

    assert "user:pass" not in redacted
    assert "secret-value" not in redacted
    assert "request_id=case-123" in redacted


def test_redact_string_fails_closed_for_malformed_url_candidates() -> None:
    value = "POST https:///hook?token=secret-value failed"

    redacted = redact_string(value, key="message")

    assert "secret-value" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_url_secrets_preserves_ipv6_host_syntax() -> None:
    value = "https://user:pass@[2001:db8::1]:8443/hook?token=secret-value"

    redacted = redact_url_secrets(value)

    assert redacted.startswith("https://[2001:db8::1]:8443/hook?")
    assert "user:pass" not in redacted
    assert "secret-value" not in redacted


def test_redact_string_fails_closed_for_excessively_nested_url_values() -> None:
    nested_url = "https://receiver.example/cb?token=secret-value"
    for _ in range(1_100):
        nested_url = f"https://gateway.example/hook?redirect={nested_url}"

    redacted = redact_string(nested_url, key="message")
    decoded = redacted
    for _ in range(10):
        decoded = unquote(decoded)

    assert "secret-value" not in decoded
    assert "[REDACTED]" in decoded


def test_redact_payload_preserves_non_url_domain_code_and_state() -> None:
    payload = {
        "code": "business-code",
        "state": "completed",
        "token_count": "17",
        "secret_label": "customer-visible label",
    }

    assert redact_payload(payload) == payload


def test_webhook_error_sanitizer_reuses_canonical_url_redaction() -> None:
    error = RuntimeError(
        "POST https://user:pass@example.com/hook?token=secret-value&safe=yes failed"
    )

    sanitized = sanitize_webhook_delivery_error(error)

    assert "user:pass" not in sanitized
    assert "secret-value" not in sanitized
    assert "token=%5BREDACTED%5D" in sanitized


def test_webhook_error_sanitizer_masks_malformed_urls_without_raising() -> None:
    sanitized = sanitize_webhook_delivery_error(
        RuntimeError("POST https://[broken?token=secret-value failed")
    )

    assert "secret-value" not in sanitized
    assert "[REDACTED]" in sanitized


def test_redact_payload_matches_hyphenated_and_case_insensitive_keys():
    payload = {"X-SESSION-Token": "abc", "safe": "value"}

    assert redact_payload(payload) == {"X-SESSION-Token": "[REDACTED]", "safe": "value"}


def test_redact_string_leaves_non_sensitive_plain_text_unchanged():
    assert redact_string("plain text", key="description") == "plain text"


def test_redact_payload_keeps_traceability_ids_but_redacts_session_tokens() -> None:
    payload = {
        "builder_session_id": "builder-session-123",
        "session_id": "runtime-session-456",
        "session_token": "very-secret",
    }

    redacted = redact_payload_with_manifest(payload)

    assert redacted.value["builder_session_id"] == "builder-session-123"
    assert redacted.value["session_id"] == "runtime-session-456"
    assert redacted.value["session_token"] == "[REDACTED]"
    assert redacted.masked_paths == ("session_token",)


@pytest.mark.parametrize(
    "key",
    [
        "authorization",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "secret",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "bearer",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth_token",
        "session_token",
        "csrf_token",
        "x_api_key",
        "client_secret",
        "webhook_secret",
        "private_key",
        "secret_key",
        "signature",
        "signed_url",
        "prefix_token",
        "prefix_secret",
        "prefix_password",
        "prefix_passwd",
        "prefix_cookie",
        "prefix_credential",
        "prefix_credentials",
        "prefix_authorization",
        "prefix_api_key",
        "prefix_apikey",
        "prefix_signature",
        "prefix_signed_url",
        "customer-access-token-value",
        "customer-refresh-token-value",
        "customer-id-token-value",
        "customer-auth-token-value",
        "customer-session-token-value",
        "service.clientSecret.value",
        "service-webhook-secret-value",
        "private key material",
        "service-secret-key-material",
        "customer-signed-url-value",
        "request authorization header",
        "user password value",
        "user passwd value",
        "browser cookie value",
        "service credential value",
        "service credentials value",
    ],
)
def test_sensitive_key_vocabulary_is_fail_closed(key: str) -> None:
    assert is_sensitive_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "token_count",
        "secret_label",
        "builder_session_id",
        "session_id",
        "public_key_id",
    ],
)
def test_sensitive_key_vocabulary_preserves_traceability_fields(
    key: str | None,
) -> None:
    assert is_sensitive_key(key) is False


def test_redaction_manifest_records_exact_nested_paths_keys_and_reasons() -> None:
    result = redact_payload_with_manifest(
        {
            "safe": [
                "Bearer bearer-secret",
                {"clientSecret": "client-secret"},
            ],
            7: "password=assignment-secret",
            "count": 3,
        },
        path="root",
    )

    assert result.value == {
        "safe": ["Bearer [REDACTED]", {"clientSecret": "[REDACTED]"}],
        "7": "password=[REDACTED]",
        "count": 3,
    }
    assert result.masked_paths == (
        "root.safe[0]",
        "root.safe[1].clientSecret",
        "root.7",
    )
    assert result.masked_fields == (
        MaskedField(
            path="root.safe[0]",
            key="safe",
            reason="authorization_credential",
        ),
        MaskedField(
            path="root.safe[1].clientSecret",
            key="clientSecret",
            reason="sensitive_key",
        ),
        MaskedField(
            path="root.7",
            key="7",
            reason="sensitive_assignment",
        ),
    )


@pytest.mark.parametrize(
    ("value", "key", "expected_value", "expected_reason"),
    [
        ("plain", "password", "[REDACTED]", "sensitive_key"),
        (
            "password=secret-value",
            "message",
            "password=[REDACTED]",
            "sensitive_assignment",
        ),
        (
            "https://example.test/cb?token=secret-value",
            "message",
            "https://example.test/cb?token=%5BREDACTED%5D",
            "sensitive_url",
        ),
        (
            "Bearer bearer-secret",
            "message",
            "Bearer [REDACTED]",
            "authorization_credential",
        ),
        ("plain", "message", "plain", None),
    ],
)
def test_redact_string_reports_the_exact_redaction_reason(
    value: str,
    key: str,
    expected_value: str,
    expected_reason: str | None,
) -> None:
    assert redact_string_with_reason(value, key=key) == StringRedactionResult(
        value=expected_value,
        reason=expected_reason,
    )


def test_url_redaction_preserves_safe_url_structure_exactly() -> None:
    assert redact_url_secrets(
        "https://user:pass@example.test:8443/path?blank=&safe=yes&token=secret#frag"
    ) == ("https://example.test:8443/path?blank=&safe=yes&token=%5BREDACTED%5D#frag")
    assert redact_url_secrets("https://example.test/path?blank=&safe=yes#frag") == (
        "https://example.test/path?blank=&safe=yes#frag"
    )
