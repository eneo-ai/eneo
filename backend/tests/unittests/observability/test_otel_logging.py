"""Tests for the OTEL Logs Data Model JSON formatter and URL redaction.

These tests do NOT require the full OTEL SDK to be initialised — they verify
the formatter output structure and the redaction helpers in isolation.

Severity convention: Python logging names are used throughout
(WARNING, not WARN; CRITICAL, not FATAL).
"""

from __future__ import annotations

import json
import logging

import pytest

from eneo.main.logging import OTELJSONFormatter, _SEVERITY_NUMBER
from eneo.main.observability import redact_url_query
from eneo.main.request_context import clear_request_context, set_request_context


@pytest.fixture(autouse=True)
def _clear_ctx():
    clear_request_context()
    yield
    clear_request_context()


def _make_record(
    message: str,
    level: int = logging.INFO,
    name: str = "test.logger",
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def _parse(record: logging.LogRecord) -> dict:
    return json.loads(OTELJSONFormatter().format(record))


# ---------------------------------------------------------------------------
# Complete parseable NDJSON structure (point 5)
# ---------------------------------------------------------------------------


def test_output_is_valid_json():
    raw = OTELJSONFormatter().format(_make_record("hello"))
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


def test_required_top_level_fields_present():
    """Backend must produce NDJSON with all mandatory fields for log aggregation."""
    out = _parse(_make_record("test message"))
    required = {"timestamp", "severity_text", "severity_number", "body", "resource"}
    missing = required - set(out.keys())
    assert not missing, f"Missing top-level fields: {missing}"


def test_resource_block_has_service_and_env():
    """resource must carry service.name, service.version, deployment.environment.name."""
    resource = _parse(_make_record("x"))["resource"]
    assert "service.name" in resource
    assert "service.version" in resource
    # OTel semantic conventions ≥1.24
    assert "deployment.environment.name" in resource
    # old key must NOT appear
    assert "deployment.environment" not in resource


def test_body_carries_log_message():
    out = _parse(_make_record("the message"))
    assert out["body"] == "the message"


def test_no_legacy_message_or_level_fields():
    """'message' and 'level' are replaced by 'body' / 'severity_text'."""
    out = _parse(_make_record("msg"))
    assert "message" not in out
    assert "level" not in out


def test_logger_name_in_attributes():
    out = _parse(_make_record("msg", name="my.module"))
    assert out["attributes"]["logger"] == "my.module"


# ---------------------------------------------------------------------------
# severity_text convention (Python names — point 6)
# ---------------------------------------------------------------------------

_LEVEL_MAP = [
    (logging.DEBUG, "DEBUG", 5),
    (logging.INFO, "INFO", 9),
    (logging.WARNING, "WARNING", 13),
    (logging.ERROR, "ERROR", 17),
    (logging.CRITICAL, "CRITICAL", 21),
]


@pytest.mark.parametrize("level_int,expected_text,expected_num", _LEVEL_MAP)
def test_severity_mapping(level_int, expected_text, expected_num):
    """severity_text uses Python logging names; severity_number follows OTel spec."""
    out = _parse(_make_record("msg", level=level_int))
    assert out["severity_text"] == expected_text
    assert out["severity_number"] == expected_num


def test_severity_number_map_complete():
    for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        assert name in _SEVERITY_NUMBER, f"{name} missing from _SEVERITY_NUMBER"


# ---------------------------------------------------------------------------
# Attributes: request context and extra fields
# ---------------------------------------------------------------------------


def test_request_context_goes_into_attributes():
    set_request_context(tenant_slug="acme", user_email="user@example.com", status_code=200)
    attrs = _parse(_make_record("msg"))["attributes"]
    assert attrs["tenant_slug"] == "acme"
    assert attrs["user_email"] == "user@example.com"
    assert attrs["status_code"] == 200


def test_extra_fields_go_into_attributes():
    out = _parse(_make_record("msg", extra={"error_id": "ab12cd34", "path": "/api/test"}))
    assert out["attributes"]["error_id"] == "ab12cd34"
    assert out["attributes"]["path"] == "/api/test"


def test_trace_id_from_context_is_top_level_not_in_attributes():
    """trace_id set in request context must appear at top level, not inside attributes."""
    set_request_context(trace_id="abcdef1234567890abcdef1234567890")
    out = _parse(_make_record("msg"))
    assert out.get("trace_id") == "abcdef1234567890abcdef1234567890"
    assert "trace_id" not in out.get("attributes", {})


def test_exception_lands_in_attributes():
    import sys

    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="oops",
            args=(),
            exc_info=sys.exc_info(),
        )
    out = json.loads(OTELJSONFormatter().format(record))
    assert "exception" in out["attributes"]
    assert "ValueError" in out["attributes"]["exception"]


# ---------------------------------------------------------------------------
# URL redaction — stdout log path (point 4)
# ---------------------------------------------------------------------------


def test_redact_url_query_no_sensitive_params():
    url = "https://example.com/api?page=1&size=20"
    assert redact_url_query(url) == url


@pytest.mark.parametrize(
    "param,value",
    [
        ("code", "AUTH_CODE"),
        ("state", "CSRF_TOKEN"),
        ("token", "MY_TOKEN"),
        ("access_token", "MY_ACCESS_TOKEN"),
        ("refresh_token", "MY_REFRESH_TOKEN"),
        ("client_secret", "MY_SECRET"),
        ("my_token_value", "SENSITIVE"),
        ("api_secret_key", "VERY_SECRET"),
    ],
)
def test_redact_url_query_sensitive_param(param, value):
    url = f"https://example.com/cb?{param}={value}&safe=ok"
    result = redact_url_query(url)
    assert f"{param}=[REDACTED]" in result, f"Expected {param} to be redacted"
    assert value not in result
    assert "safe=ok" in result


def test_redact_url_query_no_query_string():
    url = "https://example.com/api/resource"
    assert redact_url_query(url) == url
