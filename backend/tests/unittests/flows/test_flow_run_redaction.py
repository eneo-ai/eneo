from __future__ import annotations

from urllib.parse import unquote

from eneo.flows.application.flow_webhook_delivery_policy import (
    sanitize_webhook_delivery_error,
)
from eneo.flows.flow_run_redaction import (
    redact_payload,
    redact_payload_with_manifest,
    redact_string,
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
