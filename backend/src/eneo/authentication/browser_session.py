import time
from collections.abc import Mapping

import jwt
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response

from eneo.main.config import Settings, get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

# The methods the gate admits without Sec-Fetch-Site and on a direct visit
# ("none"); a same-origin navigation can send them with the session cookie.
SAFE_METHODS = frozenset({"GET", "HEAD"})

# One session name per installation, chosen by environment, never by request.
# ``__Host-`` makes the browser refuse a value planted from a sibling host.
SESSION_COOKIE = "__Host-eneo_web"
DEV_SESSION_COOKIE = "eneo_web"
TXN_COOKIE = "__Host-eneo_oidc_txn"
# Not eneo_oidc_txn: localhost cookies are shared across ports, so it would
# collide with web-next's own txn cookie.
DEV_TXN_COOKIE = "eneo_web_txn"
# web-next's session and txn cookies, also cleared at logout.
NEXT_ERA_COOKIES = ("eneo_session", "eneo_oidc_txn", "eneo_federation_txn")


def browser_request_allowed(method: str, headers: Mapping[str, str]) -> bool:
    """Whether a request may authenticate with the browser session cookie.

    ``headers`` must look names up case-insensitively, as Starlette's
    ``Headers`` does. ``Sec-Fetch-Site`` decides alone when present. Supported
    browsers always send it, so a request without it is a same-origin read or a
    non-browser client; it may only read, and only without ``Origin``, which
    every cross-origin CORS request carries.
    """
    safe = method.upper() in SAFE_METHODS
    site = headers.get("sec-fetch-site")
    if site is None:
        return safe and "origin" not in headers
    site = site.strip().lower()
    if site == "same-origin":
        return True
    if site == "none":
        return safe
    return False


def gate_allows(request: Request) -> bool:
    """``browser_request_allowed`` for a request, logging each refusal.

    The log names the request and its fetch metadata only: never cookies,
    other headers or the query string.
    """
    if browser_request_allowed(request.method, request.headers):
        return True
    logger.warning(
        "browser_origin_refused",
        extra={
            "method": request.method,
            "path": request.url.path,
            "sec_fetch_site": request.headers.get("sec-fetch-site", "missing"),
            "origin": request.headers.get("origin"),
        },
    )
    return False


def session_cookie_name(settings: Settings) -> str:
    return DEV_SESSION_COOKIE if settings.is_development else SESSION_COOKIE


def txn_cookie_name(settings: Settings) -> str:
    return DEV_TXN_COOKIE if settings.is_development else TXN_COOKIE


def session_cookie(request: HTTPConnection, settings: Settings) -> str | None:
    """The session cookie's value, read exactly from the raw Cookie headers.

    Only a pair named exactly like the session counts, and only when it is the
    only one. Starlette's parser strips names of any whitespace, including
    U+00A0 and U+0085, and lets the last duplicate win, so a sibling host could
    plant the name with a leading U+00A0, which the browser does not treat as
    ``__Host-``, and have it read as the session.
    """
    name = session_cookie_name(settings)
    pairs = (
        pair.strip(" \t").partition("=")
        for header in request.headers.getlist("cookie")
        for pair in header.split(";")
    )
    values = [value for key, separator, value in pairs if separator and key == name]
    if len(values) != 1:
        return None
    return values[0] or None


def session_token_from_request(request: Request) -> str | None:
    """The session cookie's token, if the setting is on and the gate allows.

    A request without the cookie returns before the gate, so header-less API
    clients never log a refusal.
    """
    settings = get_settings()
    if not settings.browser_session_enabled:
        return None
    token = session_cookie(request, settings)
    if not token:
        return None
    return token if gate_allows(request) else None


def _set_cookie(
    response: Response, name: str, value: str, max_age: int, settings: Settings
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=not settings.is_development,
        httponly=True,
        samesite="lax",
    )


def set_session_cookie(response: Response, token: str, *, settings: Settings) -> None:
    """Hand the browser a token just issued, for exactly its remaining life.

    ``exp`` is read unverified: the token comes from this process, not from
    the request.
    """
    exp = jwt.decode(token, options={"verify_signature": False})["exp"]
    _set_cookie(
        response,
        session_cookie_name(settings),
        token,
        max(0, int(exp - time.time())),
        settings,
    )


def clear_session_cookies(response: Response, *, settings: Settings) -> None:
    """Delete the session, txn and web-next cookies with the attributes they
    were set with, so the browser matches and drops each one."""
    names = (session_cookie_name(settings), txn_cookie_name(settings))
    for name in (*names, *NEXT_ERA_COOKIES):
        _set_cookie(response, name, "", 0, settings)
