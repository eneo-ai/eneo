"""Error text that is safe to show to the people using the product.

Exceptions from HTTP clients, the database and Redis carry request URLs (a
SharePoint download URL holds a bearer token in its query), SQL with its bound
parameters and internal host names. Every place that turns an error into text
for users, and every place that serves such text, goes through
``user_visible_error``, so rows written before it existed are cleaned too.
"""

from __future__ import annotations

import re

import aiohttp
import httpx
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

MAX_ERROR_TEXT_LENGTH = 500
# Nothing beyond this survives the final cap, so the patterns stop here.
_MAX_SCANNED_LENGTH = 8 * MAX_ERROR_TEXT_LENGTH

DATABASE_ERROR = "Database error"
CACHE_ERROR = "Cache service error"
CONNECTION_ERROR = "Connection error"
TIMEOUT_ERROR = "Request timed out"

_REDACTED = "[redacted]"
_DATABASE_DRIVERS = frozenset({"sqlalchemy", "asyncpg", "psycopg", "psycopg2"})

# Where SQLAlchemy's or a driver's own text starts: "(module.Class) ...",
# "[SQL: ...]", "[parameters: ...]" and the like. Everything from there on is
# replaced, so neither statements nor bound values survive.
_DATABASE_TEXT = re.compile(
    r"\((?:sqlalchemy|asyncpg|psycopg2?|builtins)\.[\w.]+\)"
    r"|\[SQL: "
    r"|\[parameters: "
    r"|\(Background on this error at: "
    r"|<class '(?:asyncpg|psycopg2?)\."
    r"|This Session's transaction has been rolled back"
)
# str() of aiohttp.ClientResponseError and httpx.HTTPStatusError.
_AIOHTTP_RESPONSE_ERROR = re.compile(
    r"\b(\d{3}), message=(?:'([^']*)'|\"([^\"]*)\"), url=(?:'[^']*'|\"[^\"]*\")"
)
_HTTPX_STATUS_ERROR = re.compile(
    r"\b(?:Informational response|Redirect response|Client error|Server error)"
    r" '(\d{3}) ([^']*)' for url '[^']*'"
    r"(?:\s+For more information check: \S+)?"
)
# Trailing punctuation stays outside, so "(see https://x/y?z=1)" keeps its ")".
_URL = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]*[^\s'\"<>),.;:]")
_SENSITIVE_PARAMETER = re.compile(
    r"(?i)\b(tempauth|access_token|refresh_token|id_token|client_secret|token"
    r"|signature|password|passwd|secret|api_key|apikey)"
    r"=[^\s&'\"),;]+"
)
# "code", "key" and "sig" also name plain fields ("status code=429"), so their
# values are only redacted when shaped like a token: 8+ characters, not all
# digits.
_SHORT_SENSITIVE_PARAMETER = re.compile(
    r"(?i)\b(code|key|sig)=(?!\d+(?:[\s&'\"),;]|$))[^\s&'\"),;]{8,}"
)
_AUTHORIZATION = re.compile(r"(?i)\b(authorization['\"]?\s*[:=]\s*['\"]?)[^'\"\n]+")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?")
# "Error 111 connecting to redis:6379", "Cannot connect to host x:443", ...
_HOST_AND_PORT = re.compile(
    r"(?i)\b(connecting to|connect to(?: host)?|reading from|writing to)"
    r"\s+(?:[A-Za-z0-9_.-]+|\[[0-9A-Fa-f:.]+\]):\d{1,5}\b"
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")


def user_visible_error(error: BaseException | str) -> str:
    """``error`` as text without URL queries, credentials, SQL or host names.

    An exception is described by its kind where its text is not for users:
    HTTP errors by their status, database and Redis errors by a short
    generic message. Text keeps everything else, so stable prefixes such as
    ``Error: ...`` or ``Unsupported file type (...)`` survive, and cleaning
    cleaned text changes nothing.
    """
    text = error if isinstance(error, str) else _describe(error)
    return _clean(text)


def _describe(error: BaseException) -> str:
    # A wrapper such as InternalHTTPException says nothing; its cause does.
    # The chain is walked, not recursed, and a cycle ends it.
    seen: set[int] = set()
    current = error
    while True:
        seen.add(id(current))
        text = _describe_one(current)
        cause = current.__cause__
        if text or cause is None or id(cause) in seen:
            return text or type(current).__name__
        current = cause


def _describe_one(error: BaseException) -> str:
    if isinstance(error, aiohttp.ClientResponseError) and error.status:
        return _http_status(error.status, error.message)
    if isinstance(error, httpx.HTTPStatusError):
        return _http_status(error.response.status_code, error.response.reason_phrase)
    if (
        isinstance(error, SQLAlchemyError)
        or type(error).__module__.partition(".")[0] in _DATABASE_DRIVERS
    ):
        return DATABASE_ERROR
    if isinstance(error, RedisError):
        return CACHE_ERROR
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return TIMEOUT_ERROR
    if isinstance(error, (aiohttp.ClientConnectionError, httpx.TransportError)):
        return CONNECTION_ERROR
    try:
        return str(error).strip()
    except Exception:  # noqa: BLE001 - an error whose text fails still has a kind
        return ""


def _http_status(status: int, reason: str | None) -> str:
    return f"HTTP {status} {_clean(reason or '')}".strip()


def _clean(text: str) -> str:
    text = text[:_MAX_SCANNED_LENGTH]
    database = _DATABASE_TEXT.search(text)
    if database is not None:
        text = text[: database.start()] + DATABASE_ERROR
        if text.count("(") > text.count(")"):
            text += ")"
    text = _AIOHTTP_RESPONSE_ERROR.sub(_aiohttp_status, text)
    text = _HTTPX_STATUS_ERROR.sub(r"HTTP \1 \2", text)
    text = _URL.sub(_without_credentials, text)
    text = _SENSITIVE_PARAMETER.sub(rf"\1={_REDACTED}", text)
    text = _SHORT_SENSITIVE_PARAMETER.sub(rf"\1={_REDACTED}", text)
    text = _AUTHORIZATION.sub(rf"\1{_REDACTED}", text)
    text = _BEARER.sub(f"Bearer {_REDACTED}", text)
    text = _JWT.sub(_REDACTED, text)
    text = _HOST_AND_PORT.sub(rf"\1 {_REDACTED}", text)
    text = _IPV4.sub(_REDACTED, text).strip()
    if len(text) > MAX_ERROR_TEXT_LENGTH:
        text = text[: MAX_ERROR_TEXT_LENGTH - 1].rstrip() + "…"
    return text


def _aiohttp_status(match: re.Match[str]) -> str:
    reason = match.group(2) if match.group(2) is not None else match.group(3)
    return f"HTTP {match.group(1)} {reason}".strip()


def _without_credentials(match: re.Match[str]) -> str:
    """The URL without user info, query string and fragment."""
    url = re.split(r"[?#]", match.group(0), maxsplit=1)[0]
    scheme, separator, rest = url.partition("://")
    authority, slash, path = rest.partition("/")
    authority = authority.rpartition("@")[2]
    return f"{scheme}{separator}{authority}{slash}{path}"
