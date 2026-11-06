from __future__ import annotations

from eneo.flows.http_transport.authored_config import (
    HttpAuth,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthoredConfig,
    HttpBodyMode,
    is_secret_sentinel,
)
from eneo.flows.http_transport.effective_url import (
    HTTP_URL_SCHEMES,
    InvalidHttpUrl,
    parse_credential_http_url,
    parse_effective_http_url,
)
from eneo.flows.http_transport.errors import HttpTransportError
from eneo.flows.http_transport.json_template import is_json_template


def credential_missing(auth: HttpAuth) -> bool:
    """Whether the auth mode needs a credential that is neither entered nor
    stored (a stored one reads as its sentinel)."""
    match auth:
        case HttpAuthBearer(token=token):
            return not token and not is_secret_sentinel(token)
        case HttpAuthApiKey(key=key):
            return not key and not is_secret_sentinel(key)
        case HttpAuthBasicAuth(username=username, password=password):
            return not username and not password and not is_secret_sentinel(password)
        case _:
            return False


def validate_authored_config(
    config: HttpAuthoredConfig,
    *,
    direction: str,
    method: str,
    max_timeout: float,
    credentials_required: bool = True,
) -> list[HttpTransportError]:
    """Validate authored config. Returns list of error codes (empty = valid).

    ``credentials_required`` False accepts an auth mode whose token, key or
    password is not entered yet: a draft is saved before the person enters it
    in the editor. Publishing and testing a connection require it."""
    errors: list[HttpTransportError] = []

    url_error = authored_url_error(config.url)
    if url_error is not None:
        errors.append(url_error)

    if config.has_declared_credentials:
        try:
            parse_credential_http_url(config.url)
        except InvalidHttpUrl:
            errors.append(HttpTransportError.CREDENTIALS_REQUIRE_HTTPS)

    if credentials_required and credential_missing(config.auth):
        errors.append(HttpTransportError.MISSING_AUTH_CREDENTIALS)

    # Body validation
    if method.upper() == "GET" and config.body.mode not in (
        HttpBodyMode.NONE,
        HttpBodyMode.AUTO,
    ):
        errors.append(HttpTransportError.BODY_NOT_ALLOWED_FOR_GET)

    if (
        config.body.mode == HttpBodyMode.JSON_TEMPLATE
        and config.body.template
        and not is_json_template(config.body.template)
    ):
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
