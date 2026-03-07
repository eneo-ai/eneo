from __future__ import annotations

from intric.flows.flow_run_redaction import redact_payload, redact_string, redact_url_secrets


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
    value = "https://user:pass@example.com/path?token=abc&safe=yes"

    assert redact_url_secrets(value) == "https://example.com/path?token=%5BREDACTED%5D&safe=yes"


def test_redact_payload_matches_hyphenated_and_case_insensitive_keys():
    payload = {"X-SESSION-Token": "abc", "safe": "value"}

    assert redact_payload(payload) == {"X-SESSION-Token": "[REDACTED]", "safe": "value"}


def test_redact_string_leaves_non_sensitive_plain_text_unchanged():
    assert redact_string("plain text", key="description") == "plain text"
