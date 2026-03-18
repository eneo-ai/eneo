from __future__ import annotations


from intric.flows.http_transport.authored_config import HttpBodyMode
from intric.flows.http_transport.normalizer import is_authored_config, normalize_legacy_config


# --- is_authored_config ---


def test_is_authored_config_true_for_config_with_auth_key() -> None:
    assert is_authored_config({"auth": {"mode": "none"}, "url": "https://example.org"}) is True


def test_is_authored_config_false_for_config_without_auth_key() -> None:
    assert is_authored_config({"url": "https://example.org", "headers": {}}) is False


def test_is_authored_config_false_for_none() -> None:
    assert is_authored_config(None) is False


def test_is_authored_config_false_for_empty_dict() -> None:
    assert is_authored_config({}) is False


# --- normalize_legacy_config: auth inference ---


def test_legacy_bearer_header_becomes_bearer_auth() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {"Authorization": "Bearer tok-123"},
        "timeout_seconds": 30,
    }

    result = normalize_legacy_config(raw)

    assert result.auth.mode == "bearer_token"
    assert result.auth.token == "tok-123"


def test_legacy_no_auth_header_becomes_none_auth() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "timeout_seconds": 30,
    }

    result = normalize_legacy_config(raw)

    assert result.auth.mode == "none"


def test_legacy_authorization_case_insensitive() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {"authorization": "Bearer tok-abc"},
    }

    result = normalize_legacy_config(raw)

    assert result.auth.mode == "bearer_token"
    assert result.auth.token == "tok-abc"


# --- normalize_legacy_config: body inference ---


def test_legacy_body_template_becomes_text_template() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "body_template": "Hello {{name}}",
    }

    result = normalize_legacy_config(raw)

    assert result.body.mode == HttpBodyMode.TEXT_TEMPLATE
    assert result.body.template == "Hello {{name}}"


def test_legacy_body_json_becomes_json_template() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "body_json": {"key": "value"},
    }

    result = normalize_legacy_config(raw)

    assert result.body.mode == HttpBodyMode.JSON_TEMPLATE
    assert result.body.template == '{"key": "value"}'


def test_legacy_no_body_becomes_auto() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
    }

    result = normalize_legacy_config(raw)

    assert result.body.mode == HttpBodyMode.AUTO
    assert result.body.template is None


def test_legacy_empty_body_template_becomes_auto() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "body_template": "   ",
    }

    result = normalize_legacy_config(raw)

    assert result.body.mode == HttpBodyMode.AUTO


# --- normalize_legacy_config: custom headers ---


def test_non_auth_headers_become_secret_custom_headers() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {
            "Authorization": "Bearer tok",
            "X-Custom": "val1",
            "X-Another": "val2",
        },
    }

    result = normalize_legacy_config(raw)

    # Authorization should NOT appear as a custom header
    names = [h.name for h in result.custom_headers]
    assert "Authorization" not in names
    assert "X-Custom" in names
    assert "X-Another" in names

    # All non-auth headers are marked secret=True
    for h in result.custom_headers:
        assert h.secret is True


# --- normalize_legacy_config: preserved fields ---


def test_url_is_preserved() -> None:
    raw = {"url": "https://example.org/api", "headers": {}}

    result = normalize_legacy_config(raw)

    assert result.url == "https://example.org/api"


def test_timeout_seconds_is_preserved() -> None:
    raw = {"url": "https://example.org/api", "headers": {}, "timeout_seconds": 60}

    result = normalize_legacy_config(raw)

    assert result.timeout_seconds == 60


def test_response_format_is_preserved() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "response_format": "json",
    }

    result = normalize_legacy_config(raw)

    assert result.response_format == "json"


def test_invalid_response_format_becomes_none() -> None:
    raw = {
        "url": "https://example.org/api",
        "headers": {},
        "response_format": "xml",
    }

    result = normalize_legacy_config(raw)

    assert result.response_format is None


# --- normalize_legacy_config: defensive defaults ---


def test_missing_url_defaults_to_empty_string() -> None:
    raw = {"headers": {}}

    result = normalize_legacy_config(raw)

    assert result.url == ""


def test_non_string_url_defaults_to_empty_string() -> None:
    raw = {"url": 12345, "headers": {}}

    result = normalize_legacy_config(raw)

    assert result.url == ""


def test_invalid_timeout_defaults_to_30() -> None:
    raw = {"url": "https://example.org/api", "headers": {}, "timeout_seconds": "bad"}

    result = normalize_legacy_config(raw)

    assert result.timeout_seconds == 30
