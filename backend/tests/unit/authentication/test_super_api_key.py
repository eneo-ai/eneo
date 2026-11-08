"""The super API key is compared in constant time, as UTF-8 bytes."""

import hmac
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request

from eneo.authentication import auth
from eneo.main.exceptions import AuthenticationException

KEY = "operator-super-key-ÅÄÖ"


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "headers": []})


def _authenticate(configured: str | None, provided: str | None) -> str:
    settings = SimpleNamespace(
        eneo_super_api_key=configured, api_key_header_name="X-API-Key"
    )
    with patch.object(auth, "get_settings", return_value=settings):
        return auth.authenticate_super_api_key(_request(), provided)


def test_the_configured_key_is_accepted():
    assert _authenticate(KEY, KEY) == KEY


@pytest.mark.parametrize(
    "provided",
    [
        pytest.param("operator-super-key-AAO", id="mismatch"),
        pytest.param(KEY[:-1], id="prefix"),
        pytest.param("ünïcödé guess", id="non-ascii-mismatch"),
        pytest.param("", id="empty"),
        pytest.param(None, id="missing"),
    ],
)
def test_any_other_key_is_refused(provided: str | None):
    with pytest.raises(AuthenticationException):
        _authenticate(KEY, provided)


@pytest.mark.parametrize("configured", [None, ""])
def test_an_unconfigured_key_admits_nobody(configured: str | None):
    with pytest.raises(AuthenticationException):
        _authenticate(configured, "")
    with pytest.raises(AuthenticationException):
        _authenticate(configured, "anything")


def test_the_comparison_is_compare_digest_on_bytes():
    with patch.object(
        auth.hmac, "compare_digest", wraps=hmac.compare_digest
    ) as compare:
        _authenticate(KEY, KEY)

    compare.assert_called_once_with(KEY.encode("utf-8"), KEY.encode("utf-8"))
