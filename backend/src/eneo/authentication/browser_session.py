import base64
import hashlib
import re
import time
from collections.abc import Mapping
from urllib.parse import unquote

import jwt
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response
from starlette.types import Scope
from yarl import URL

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

DEFAULT_LANDING = "/spaces/personal/chat"
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def safe_next_path(value: str | None) -> str:
    """The SPA's safeNextPath contract, checked against their shared case file.

    Validate the decoded path after browser dot-segment normalization. Decoding
    before parsing would turn an encoded ? or # into a different path boundary.
    Keep the original query encoding when returning an accepted destination.
    """
    if not value or not value.startswith("/") or _BAD_ESCAPE.search(value):
        return DEFAULT_LANDING
    try:
        decoded = unquote(value, errors="strict")
        for candidate in (value, decoded):
            if (
                candidate.startswith("//")
                or "\\" in candidate
                or any(ord(char) <= 31 or ord(char) == 127 for char in candidate)
            ):
                return DEFAULT_LANDING
        # Yarl already owns URL normalization in this backend. Like WHATWG URL,
        # remove trailing spaces before parsing; Yarl 1.25 still encodes them.
        url = URL("https://login-destination.invalid" + value.rstrip(" "))
        path = unquote(url.raw_path, errors="strict")
        if "//" in path or any(part in (".", "..") for part in path.split("/")):
            return DEFAULT_LANDING
        if any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in ("/login", "/logout", "/api", "/auth", "/_next")
        ):
            return DEFAULT_LANDING
    except (UnicodeError, ValueError):
        return DEFAULT_LANDING
    return value


# The session generation: on a response, the cookie session the request was
# admitted with (the bootstrap probe also names a rejected cookie for logout);
# on a request, the one the sending page was loaded with. A
# fingerprint, neither a credential nor a CSRF token.
SESSION_GENERATION_HEADER = "Eneo-Session-Generation"
# Request-state keys: the generation of the cookie OAUTH2_SCHEME selected, and
# the same value once canonical authentication admitted the request.
_SELECTED_GENERATION = "browser_session_selected_generation"
_ADMITTED_GENERATION = "browser_session_admitted_generation"


class SessionGenerationMismatchError(Exception):
    """The page that sent the request was loaded under another session."""

    code = "session_generation_mismatch"

    def __init__(self) -> None:
        super().__init__("The browser session changed after this page was loaded.")


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
    return _cookie_value(request, session_cookie_name(settings))


def transaction_cookie(request: HTTPConnection, settings: Settings) -> str | None:
    return _cookie_value(request, txn_cookie_name(settings))


def _cookie_value(request: HTTPConnection, name: str) -> str | None:
    """A browser auth cookie's value, read exactly from the raw Cookie headers.

    Only a pair with the exact cookie name counts, and only when it is the
    only one. Starlette's parser strips names of any whitespace, including
    U+00A0 and U+0085, and lets the last duplicate win, so a sibling host could
    plant the name with a leading U+00A0, which the browser does not treat as
    ``__Host-``, and have it read as the session.
    """
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
    if not token or not gate_allows(request):
        return None
    refuse_superseded_session(request, token)
    generation = session_generation(token)
    request.scope.setdefault("state", {})[_SELECTED_GENERATION] = generation
    return token


def session_generation(token: str) -> str:
    """The generation of a session: 128 bits of the SHA-256 of its exact token.

    A different credential has a different generation, and it reveals
    nothing of the token. Not a session id: re-issuing an identical token
    repeats it, which is fine, since only a different credential must never be
    taken for the one a page was loaded with.
    """
    digest = hashlib.sha256(token.encode()).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def admit_session(connection: HTTPConnection) -> None:
    """Record that canonical authentication admitted this request.

    When its credential was the session cookie, the response names the
    cookie's generation (``ResponseHeadersMiddleware``). Selection alone is
    not enough: the cookie is read before its token is verified.
    """
    state = connection.scope.get("state", {})
    if _SELECTED_GENERATION in state:
        state[_ADMITTED_GENERATION] = state[_SELECTED_GENERATION]


def admitted_session_generation(scope: Scope) -> str | None:
    return scope.get("state", {}).get(_ADMITTED_GENERATION)


def response_session_generation(scope: Scope) -> str | None:
    """Name an admitted session, or the bootstrap cookie that logout may clear.

    A rejected probe must still let its fresh document clear an expired or
    restricted cookie without risking a replacement session. Selection already
    checked the origin gate and any expected generation. Only a 204 probe admits
    authenticated work; a fingerprint on a refusal is solely a logout binding.
    Other API responses continue to require canonical admission.
    """
    if scope.get("method") == "GET" and scope.get("path") == "/api/v1/auth/session/":
        return scope.get("state", {}).get(_SELECTED_GENERATION)
    return admitted_session_generation(scope)


def refuse_superseded_session(request: Request, token: str) -> None:
    """Refuse a request from a page loaded under another session.

    The page names the generation it was loaded with; when the cookie now
    holds another credential (another tab signed in or out), acting on it
    would act as someone the page does not show. Only bootstrap reads may
    omit the header; writes must name their expected session. The domain
    exception handler logs the refusal.
    """
    expected = request.headers.get(SESSION_GENERATION_HEADER)
    if expected is None and request.method in SAFE_METHODS:
        return
    if expected != session_generation(token):
        raise SessionGenerationMismatchError()


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


def set_transaction_cookie(
    response: Response, value: str, *, settings: Settings
) -> None:
    _set_cookie(
        response,
        txn_cookie_name(settings),
        value,
        settings.oidc_state_ttl_seconds,
        settings,
    )


def clear_transaction_cookie(response: Response, *, settings: Settings) -> None:
    _set_cookie(response, txn_cookie_name(settings), "", 0, settings)


def clear_session_cookies(response: Response, *, settings: Settings) -> None:
    """Delete the session, txn and web-next cookies with the attributes they
    were set with, so the browser matches and drops each one."""
    names = (session_cookie_name(settings), txn_cookie_name(settings))
    for name in (*names, *NEXT_ERA_COOKIES):
        _set_cookie(response, name, "", 0, settings)
