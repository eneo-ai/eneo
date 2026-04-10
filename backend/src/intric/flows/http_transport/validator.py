from __future__ import annotations

import json
from urllib.parse import urlparse

from intric.flows.http_transport.authored_config import (
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBodyMode,
)
from intric.flows.http_transport.errors import HttpTransportError


def _is_secret_sentinel(value: object) -> bool:
    return (
        isinstance(value, dict)
        and cast(dict[str, object], value).get("$secret") == "stored"
    )


def validate_authored_config(
    config: HttpAuthoredConfig,
    *,
    direction: str,
    method: str,
    max_timeout: float = 120.0,
) -> list[HttpTransportError]:
    """Validate authored config. Returns list of error codes (empty = valid)."""
    errors: list[HttpTransportError] = []

    # URL validation
    if not config.url.strip():
        errors.append(HttpTransportError.MISSING_URL)
    else:
        try:
            parsed = urlparse(config.url.strip())
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                errors.append(HttpTransportError.INVALID_URL)
        except Exception:
            errors.append(HttpTransportError.INVALID_URL)

    # Auth credentials validation (skip sentinel values — already stored)
    match config.auth:
        case HttpAuthBearer(token=token):
            if not token and not _is_secret_sentinel(token):
                errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)
        case HttpAuthApiKey(key=key):
            if not key and not _is_secret_sentinel(key):
                errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)
        case HttpAuthBasicAuth(username=username, password=password):
            if not username and not password and not _is_secret_sentinel(password):
                errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)
        case HttpAuthNone():
            pass

    # Body validation
    if method.upper() == "GET" and config.body.mode not in (
        HttpBodyMode.NONE,
        HttpBodyMode.AUTO,
    ):
        errors.append(HttpTransportError.BODY_NOT_ALLOWED_FOR_GET)

    if config.body.mode == HttpBodyMode.JSON_TEMPLATE and config.body.template:
        try:
            json.loads(config.body.template)
        except (json.JSONDecodeError, ValueError):
            # Allow template expressions — they won't parse as JSON
            if "{{" not in config.body.template:
                errors.append(HttpTransportError.INVALID_BODY_JSON)

    # Timeout validation
    if config.timeout_seconds < 1 or config.timeout_seconds > max_timeout:
        errors.append(HttpTransportError.TIMEOUT_OUT_OF_RANGE)

    return errors


from typing import cast
