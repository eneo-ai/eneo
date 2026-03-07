from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_FIELD_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "session",
    "credential",
    "bearer",
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-~+/]+=*")


def is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False
    key_lower = key.lower().replace("-", "_").replace(".", "_")
    return any(fragment in key_lower for fragment in _SENSITIVE_FIELD_FRAGMENTS)


def redact_url_secrets(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{host}{port}"

    if not parse_qsl(parsed.query, keep_blank_values=True):
        if parsed.username is None and parsed.password is None:
            return value
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    redacted_query = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if is_sensitive_key(key):
            redacted_query.append((key, _REDACTED_VALUE))
        else:
            redacted_query.append((key, item_value))

    return urlunsplit(
        (
            parsed.scheme,
            netloc if parsed.username or parsed.password else parsed.netloc,
            parsed.path,
            urlencode(redacted_query, doseq=True),
            parsed.fragment,
        )
    )


def redact_string(value: str, *, key: str | None) -> str:
    if is_sensitive_key(key):
        return _REDACTED_VALUE
    if "://" in value:
        value = redact_url_secrets(value)
    return _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", value)


def redact_payload(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: redact_payload(item_value, key=item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_string(value, key=key)
    return value
