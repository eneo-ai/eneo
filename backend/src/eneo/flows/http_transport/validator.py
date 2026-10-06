from __future__ import annotations

import json

from eneo.flows.http_transport.authored_config import (
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBodyMode,
    is_secret_sentinel,
)
from eneo.flows.http_transport.effective_url import (
    HTTP_URL_SCHEMES,
    InvalidHttpUrl,
    parse_effective_http_url,
)
from eneo.flows.http_transport.errors import HttpTransportError


def validate_authored_config(
    config: HttpAuthoredConfig,
    *,
    direction: str,
    method: str,
    max_timeout: float,
) -> list[HttpTransportError]:
    """Validate authored config. Returns list of error codes (empty = valid)."""
    errors: list[HttpTransportError] = []

    url_error = authored_url_error(config.url)
    if url_error is not None:
        errors.append(url_error)

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


def authored_url_error(url: str) -> HttpTransportError | None:
    """The URL's defect that can be known before the request.

    A fixed URL is validated whole. A URL with a template is only known once it
    is filled, at the request, but what the template does not fill is authored
    literally and is validated now: a scheme written before the first template
    must be http or https, and userinfo is refused even when the host is a
    template, so deferring it to interpolation would let the credential be
    stored.
    """
    if not _contains_template_marker(url):
        return validate_http_url(url)
    fixed_prefix = url.split("{{", 1)[0].strip()
    if "://" in fixed_prefix:
        scheme = fixed_prefix.split("://", 1)[0].lower()
        if scheme not in HTTP_URL_SCHEMES:
            return HttpTransportError.INVALID_URL
    if contains_url_userinfo(url):
        return HttpTransportError.INVALID_URL
    return None


def validate_http_url(url: str) -> HttpTransportError | None:
    if not url.strip():
        return HttpTransportError.MISSING_URL
    try:
        parse_effective_http_url(url)
    except InvalidHttpUrl:
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
