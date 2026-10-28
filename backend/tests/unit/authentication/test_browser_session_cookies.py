"""The real Set-Cookie headers of the browser session, spelled out once in
``tests.unit.browser_session_test_utils``."""

import pytest
from freezegun import freeze_time
from starlette.responses import Response

from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session import (
    clear_session_cookies,
    set_session_cookie,
)
from eneo.main.config import Settings, get_settings
from tests.fixtures import TEST_USER
from tests.unit.browser_session_test_utils import expected_set_cookie

NEXT_ERA = ("eneo_session", "eneo_oidc_txn", "eneo_federation_txn")
# SimpleCookie renders an empty value as a quoted empty string.
EMPTY = '""'


def settings_for(environment: str) -> Settings:
    return get_settings().model_copy(
        update={"browser_session_enabled": True, "environment": environment}
    )


def set_cookies(response: Response) -> list[str]:
    return response.headers.getlist("set-cookie")


@pytest.mark.parametrize(
    ("environment", "name", "production"),
    [("production", "__Host-eneo_web", True), ("development", "eneo_web", False)],
)
@freeze_time("2026-10-28 12:00:00")
def test_session_cookie_lives_as_long_as_the_token(
    environment: str, name: str, production: bool
):
    token = AuthService().create_access_token_for_user(TEST_USER, expires_in=15)
    response = Response()

    set_session_cookie(response, token, settings=settings_for(environment))

    assert set_cookies(response) == [
        expected_set_cookie(name, token, 15 * 60, production=production)
    ]
    assert "domain" not in set_cookies(response)[0].lower()


@freeze_time("2026-10-28 12:00:00")
def test_expired_token_gets_no_lifetime():
    token = AuthService().create_access_token_for_user(TEST_USER, expires_in=-1)
    response = Response()

    set_session_cookie(response, token, settings=settings_for("production"))

    assert set_cookies(response) == [
        expected_set_cookie("__Host-eneo_web", token, 0, production=True)
    ]


@pytest.mark.parametrize(
    ("environment", "session", "txn", "production"),
    [
        ("production", "__Host-eneo_web", "__Host-eneo_oidc_txn", True),
        ("development", "eneo_web", "eneo_web_txn", False),
    ],
)
def test_clearing_matches_the_attributes_they_were_set_with(
    environment: str, session: str, txn: str, production: bool
):
    response = Response()

    clear_session_cookies(response, settings=settings_for(environment))

    assert set_cookies(response) == [
        expected_set_cookie(name, EMPTY, 0, production=production)
        for name in (session, txn, *NEXT_ERA)
    ]
