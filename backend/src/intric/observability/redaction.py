"""Helpers for masking sensitive information in logs."""

from __future__ import annotations

from typing import Any, Dict


def redact_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value

    local, domain = value.split("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def redact_secret(_: Any) -> str:
    return "[REDACTED]"


SENSITIVE_KEYS = {
    "client_secret",
    "access_token",
    "refresh_token",
    "id_token",
    "password",
    "secret",
}


def sanitize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with sensitive fields masked."""

    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if key in SENSITIVE_KEYS:
            sanitized[key] = redact_secret(value)
        else:
            sanitized[key] = value
    return sanitized
