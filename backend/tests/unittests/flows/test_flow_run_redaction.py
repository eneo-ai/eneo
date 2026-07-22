from __future__ import annotations

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
