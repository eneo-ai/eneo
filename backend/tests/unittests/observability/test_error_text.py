"""Error text shown to users carries no URL query, credential, SQL or host name."""

import asyncio

import aiohttp
import httpx
import pytest
import sqlalchemy as sa
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError
from yarl import URL

from eneo.main.exceptions import InternalHTTPException
from eneo.observability.error_text import (
    MAX_ERROR_TEXT_LENGTH,
    user_visible_error,
)

SIGNED_URL = (
    "https://contoso.sharepoint.com/sites/KS/_layouts/15/download.aspx"
    "?UniqueId=abc&Translate=false&tempauth=v1.eyJhdWQiOiJ4In0.c2lnbmF0dXJl"
    "&ApiVersion=2.0#frag"
)


def _response_error(status: int, reason: str, url: str = SIGNED_URL):
    request_url = URL(url)
    return aiohttp.ClientResponseError(
        RequestInfo(
            request_url,
            "GET",
            CIMultiDictProxy(CIMultiDict({"Authorization": "Bearer graph-token"})),
            request_url,
        ),
        (),
        status=status,
        message=reason,
    )


def _database_error(error_class: type[sa.exc.DBAPIError] = sa.exc.IntegrityError):
    return error_class(
        "INSERT INTO info_blobs (title, url) VALUES (%(title)s, %(url)s)",
        {"title": "Lönelista.xlsx", "url": "https://contoso.sharepoint.com/x"},
        Exception('duplicate key value violates unique constraint "info_blobs_pkey"'),
    )


def _with_cause(error: Exception, cause: Exception) -> Exception:
    try:
        raise error from cause
    except Exception as raised:
        return raised


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            _response_error(403, "Forbidden"), "HTTP 403 Forbidden", id="http"
        ),
        pytest.param(_response_error(503, ""), "HTTP 503", id="http-without-reason"),
        pytest.param(
            httpx.HTTPStatusError(
                "Client error '401 Unauthorized' for url 'https://login.example/t?code=x'",
                request=httpx.Request("POST", "https://login.example/t?code=x"),
                response=httpx.Response(401),
            ),
            "HTTP 401 Unauthorized",
            id="httpx",
        ),
        pytest.param(_database_error(), "Database error", id="integrity"),
        pytest.param(
            _database_error(sa.exc.OperationalError), "Database error", id="operational"
        ),
        pytest.param(
            sa.exc.PendingRollbackError(
                "This Session's transaction has been rolled back"
            ),
            "Database error",
            id="pending-rollback",
        ),
        pytest.param(
            RedisConnectionError("Error 111 connecting to redis.internal:6379."),
            "Cache service error",
            id="redis-connection",
        ),
        pytest.param(
            RedisResponseError("WRONGTYPE Operation against a key"),
            "Cache service error",
            id="redis-response",
        ),
        pytest.param(asyncio.TimeoutError(), "Request timed out", id="timeout"),
        pytest.param(
            aiohttp.ClientConnectionError("Cannot connect to host db.internal:5432"),
            "Connection error",
            id="connection",
        ),
        pytest.param(
            _with_cause(
                InternalHTTPException(), aiohttp.ServerDisconnectedError("gone")
            ),
            "Connection error",
            id="empty-wrapper-uses-its-cause",
        ),
        pytest.param(KeyError(), "KeyError", id="empty-message"),
        pytest.param(
            ValueError("No download URL available for file 'a.docx' (item_id=01AB)"),
            "No download URL available for file 'a.docx' (item_id=01AB)",
            id="own-message",
        ),
    ],
)
def test_exceptions_are_described_by_their_kind(error, expected):
    assert user_visible_error(error) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            f"Error: 403, message='Forbidden', url='{SIGNED_URL}'",
            "Error: HTTP 403 Forbidden",
            id="stored-aiohttp-error",
        ),
        pytest.param(
            f'Error: 404, message="It\'s gone", url="{SIGNED_URL}"',
            "Error: HTTP 404 It's gone",
            id="stored-aiohttp-error-double-quoted",
        ),
        pytest.param(
            "Client error '429 Too Many Requests' for url 'https://graph.microsoft.com/"
            "v1.0/x?token=abc'\nFor more information check: "
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429",
            "HTTP 429 Too Many Requests",
            id="stored-httpx-error",
        ),
        pytest.param(
            "Could not remove out-of-scope: " + str(_database_error()),
            "Could not remove out-of-scope: Database error",
            id="stored-sql",
        ),
        pytest.param(
            "Orphan cleanup skipped: could not list SharePoint items ("
            + str(_database_error())
            + ")",
            "Orphan cleanup skipped: could not list SharePoint items (Database error)",
            id="stored-sql-in-parentheses",
        ),
        pytest.param(
            f"Download failed: {SIGNED_URL}",
            "Download failed: https://contoso.sharepoint.com/sites/KS/_layouts/15/"
            "download.aspx",
            id="url-query-and-fragment",
        ),
        pytest.param(
            "(see https://user:pass@contoso.sharepoint.com/a?sig=1)",
            "(see https://contoso.sharepoint.com/a)",
            id="url-user-info",
        ),
        pytest.param(
            "v1.0/drives/b!x/root/delta?token=abc&tempauth=def",
            "v1.0/drives/b!x/root/delta?token=[redacted]&tempauth=[redacted]",
            id="relative-url-parameters",
        ),
        pytest.param(
            "status code=429, retry key=12345678, sig=ab",
            "status code=429, retry key=12345678, sig=ab",
            id="short-keys-naming-plain-fields",
        ),
        pytest.param(
            "code=0.AXsAbCdEf-ghij&key=AbCdEfGh1&sig=abcdefgh",
            "code=[redacted]&key=[redacted]&sig=[redacted]",
            id="short-keys-with-token-values",
        ),
        pytest.param(
            "api_key=ab token=1 secret=x",
            "api_key=[redacted] token=[redacted] secret=[redacted]",
            id="credential-keys-redacted-whatever-the-value",
        ),
        pytest.param(
            "headers={'Authorization': 'Bearer graph-token', 'Accept': 'json'}",
            "headers={'Authorization': '[redacted]', 'Accept': 'json'}",
            id="authorization-header",
        ),
        pytest.param(
            "sent Bearer 0123456789abcdefghij.klmnop to the host",
            "sent Bearer [redacted] to the host",
            id="bearer-token",
        ),
        pytest.param(
            "token v1.eyJhdWQiOiJodHRwczovL3gifQ.c2lnbmF0dXJl inline",
            "token v1.[redacted] inline",
            id="jwt",
        ),
        pytest.param(
            "Error: Error 111 connecting to redis.internal:6379. Connection refused.",
            "Error: Error 111 connecting to [redacted]. Connection refused.",
            id="stored-redis-host",
        ),
        pytest.param(
            "Cannot connect to host db.internal:5432 ssl:default [10.0.0.7:5432]",
            "Cannot connect to host [redacted] ssl:default [[redacted]]",
            id="host-and-address",
        ),
    ],
)
def test_stored_text_is_cleaned(text, expected):
    assert user_visible_error(text) == expected


@pytest.mark.parametrize(
    "reason",
    [
        "Unsupported file type (legacy Word .doc, save as .docx)",
        "No text layer (scanned document; OCR is not supported)",
        "Empty or unreadable content",
        "File too large (exceeds 50 MB limit)",
        "Exceeds extraction limit (5000000 bytes of text)",
        "Exceeds extraction limit (500 PDF pages)",
        "Error: Password-protected file",
        "Error: Corrupt or malformed file",
        "Error: Incomplete download of 'Budget 2026 (slutlig).pdf' (10 of 20 bytes)",
        "Error: KeyError while extracting docx",
        "Could not list folder contents: HTTP 403 Forbidden",
        "Folder scope path unavailable",
        "SharePoint credentials are invalid or expired; an administrator must "
        "reconnect the integration",
    ],
)
def test_the_stable_reasons_the_frontends_translate_are_unchanged(reason):
    assert user_visible_error(reason) == reason


def test_cleaning_is_idempotent():
    samples = [
        _response_error(403, "Forbidden"),
        _database_error(),
        f"Error: 403, message='Forbidden', url='{SIGNED_URL}'",
        "Could not remove out-of-scope: " + str(_database_error()),
        "x" * (MAX_ERROR_TEXT_LENGTH * 2),
        f"a {SIGNED_URL} b Bearer {'t' * 40} c redis.internal connecting to h:1",
    ]
    for sample in samples:
        once = user_visible_error(sample)
        assert user_visible_error(once) == once


def test_long_text_is_capped():
    text = user_visible_error("Error: " + "x" * 2000)

    assert len(text) == MAX_ERROR_TEXT_LENGTH
    assert text.startswith("Error: x") and text.endswith("…")


def test_very_long_text_is_scanned_only_as_far_as_the_cap_can_show():
    text = user_visible_error("x" * 100_000 + f" {SIGNED_URL}")

    assert len(text) == MAX_ERROR_TEXT_LENGTH
    assert "tempauth" not in text


def test_nothing_secret_survives_any_path():
    texts = [
        user_visible_error(_response_error(403, "Forbidden")),
        user_visible_error(str(_response_error(403, "Forbidden"))),
        user_visible_error(repr(_response_error(403, "Forbidden"))),
        user_visible_error(_database_error()),
        user_visible_error("Error: " + str(_database_error())),
    ]
    for text in texts:
        for secret in ("tempauth", "eyJ", "graph-token", "INSERT INTO", "Lönelista"):
            assert secret not in text


def test_a_cause_chain_that_loops_back_is_described_by_its_kind():
    first, second = InternalHTTPException(), InternalHTTPException()
    first.__cause__, second.__cause__ = second, first

    assert user_visible_error(first) == "InternalHTTPException"


def test_a_long_chain_of_silent_wrappers_still_reaches_its_cause():
    error: BaseException = aiohttp.ServerDisconnectedError("gone")
    for _ in range(5_000):
        wrapper = InternalHTTPException()
        wrapper.__cause__ = error
        error = wrapper

    assert user_visible_error(error) == "Connection error"


def test_an_error_whose_text_cannot_be_built_is_described_by_its_kind():
    class Unprintable(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no text")

    assert user_visible_error(Unprintable()) == "Unprintable"
