from __future__ import annotations

import json
from urllib.parse import urlparse

from eneo.flows.http_transport.authored_config import (
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBodyMode,
    is_secret_sentinel,
)
from eneo.flows.http_transport.errors import HttpTransportError


def validate_authored_config(
    config: HttpAuthoredConfig,
    *,
    direction: str,
    method: str,
    max_timeout: float = 120.0,
) -> list[HttpTransportError]:
    """Validate authored config. Returns list of error codes (empty = valid)."""
    errors: list[HttpTransportError] = []

    url_error = validate_http_url(config.url)
    # Template URLs are validated after interpolation by the draft/runtime sender.
    if url_error is not None and not _contains_template_marker(config.url):
        errors.append(url_error)
    elif contains_url_userinfo(config.url):
        # Userinfo is authored literally even when the host is a template, so
        # deferring it to interpolation would let the credential be stored.
        errors.append(HttpTransportError.INVALID_URL)

    # Auth credentials validation (skip sentinel values — already stored)
    match config.auth:
        case HttpAuthBearer(token=token):
            if not token and not is_secret_sentinel(token):
                errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)
        case HttpAuthApiKey(key=key):
            if not key and not is_secret_sentinel(key):
                errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)
        case HttpAuthBasicAuth(username=username, password=password):
            if not username and not password and not is_secret_sentinel(password):
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


def validate_http_url(url: str) -> HttpTransportError | None:
    if not url.strip():
        return HttpTransportError.MISSING_URL
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return HttpTransportError.INVALID_URL
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return HttpTransportError.INVALID_URL
    if contains_url_userinfo(url):
        return HttpTransportError.INVALID_URL
    return None


def contains_url_userinfo(url: str) -> bool:
    """Whether the URL authority carries userinfo, template markers or not.

    Userinfo would put a credential in a field that is stored, logged and
    previewed as an ordinary URL, outside the encrypted auth fields entirely.
    The authority is read from the literal string rather than through a parser
    so that a templated host does not hide an authored ``user:pass@``.
    """
    stripped = url.strip()
    scheme_separator = stripped.find("://")
    if scheme_separator == -1:
        return False
    authority = stripped[scheme_separator + len("://") :]
    for terminator in ("/", "?", "#"):
        end = authority.find(terminator)
        if end != -1:
            authority = authority[:end]
    return "@" in authority


def _contains_template_marker(value: str) -> bool:
    return "{{" in value
