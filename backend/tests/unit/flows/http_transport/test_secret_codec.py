"""What a reader of a saved HTTP config learns about its credentials: that a
stored one exists, never its value, and that a missing one is still missing."""

from __future__ import annotations

from eneo.flows.http_transport import redact_persisted_config
from eneo.flows.http_transport.authored_config import SECRET_SENTINEL


def test_a_credential_not_entered_yet_reads_as_missing_not_stored():
    saved = {
        "url": "https://api.example.se/cases",
        "auth": {"mode": "api_key", "header_name": "X-API-Key", "key": ""},
        "custom_headers": [{"name": "X-Signature", "value": "", "secret": True}],
    }

    redacted = redact_persisted_config(saved)

    assert redacted is not None
    assert redacted["auth"] == {
        "mode": "api_key",
        "header_name": "X-API-Key",
        "key": "",
    }
    assert redacted["custom_headers"][0]["value"] == ""


def test_a_stored_credential_reads_as_the_sentinel_only():
    saved = {
        "url": "https://api.example.se/cases",
        "auth": {"mode": "api_key", "header_name": "X-API-Key", "key": "enc:abc"},
        "custom_headers": [{"name": "X-Signature", "value": "enc:def", "secret": True}],
    }

    redacted = redact_persisted_config(saved)

    assert redacted is not None
    assert redacted["auth"]["key"] == SECRET_SENTINEL
    assert redacted["custom_headers"][0]["value"] == SECRET_SENTINEL
    assert "enc:" not in str(redacted)
