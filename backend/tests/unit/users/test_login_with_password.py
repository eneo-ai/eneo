"""login_with_password owns the password flow every login endpoint shares."""

from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from eneo.authentication.auth_models import AccessToken
from eneo.authentication.login_attempts import LoginAttempt
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.users import user_router
from eneo.users.user_service import UserService

EMAIL = "login@example.com"
PASSWORD = "LoginCredential-SENTINEL-123!"
TOKEN = AccessToken(access_token="issued-token", token_type="bearer")


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("10.0.0.1", 1),
        }
    )


@pytest.fixture
def login(monkeypatch: pytest.MonkeyPatch):
    service = AsyncMock(spec=UserService)
    service.login.return_value = TOKEN
    count = AsyncMock(return_value=LoginAttempt(True, 4, 600))
    clear = AsyncMock()
    monkeypatch.setattr(user_router, "count_login_attempt", count)
    monkeypatch.setattr(user_router, "clear_login_attempts", clear)
    container = Container(
        user_service=providers.Object(service),
        redis_client=providers.Object(object()),
    )

    async def call(email: str = EMAIL, password: str = PASSWORD) -> AccessToken:
        return await user_router.login_with_password(
            request=_request(), email=email, password=password, container=container
        )

    call.service, call.count, call.clear = service, count, clear  # type: ignore[attr-defined]
    return call


async def test_login_with_password_returns_token_and_clears_attempts(login):
    assert await login() == TOKEN
    login.service.login.assert_awaited_once()
    login.clear.assert_awaited_once()


async def test_login_with_password_raises_401_with_attempts_remaining(login):
    login.service.login.side_effect = AuthenticationException("bad")

    with pytest.raises(HTTPException) as caught:
        await login()

    assert caught.value.status_code == 401
    assert caught.value.detail["code"] == "invalid_credentials"
    assert caught.value.detail["attempts_remaining"] == 4
    login.clear.assert_not_awaited()


async def test_login_with_password_raises_429_with_retry_after(login):
    login.count.return_value = LoginAttempt(False, 0, 300)

    with pytest.raises(HTTPException) as caught:
        await login()

    assert caught.value.status_code == 429
    assert caught.value.detail["code"] == "too_many_login_attempts"
    assert caught.value.detail["retry_after_seconds"] == 300
    assert caught.value.headers["Retry-After"] == "300"
    login.service.login.assert_not_awaited()


@pytest.mark.parametrize(
    ("email", "password", "location"),
    [
        ("not-an-email", PASSWORD, ["body", "username"]),
        (EMAIL, "short", ["body", "password"]),
    ],
)
async def test_login_with_password_validation_reports_form_locations(
    login, email: str, password: str, location: list[str]
):
    with pytest.raises(RequestValidationError) as caught:
        await login(email=email, password=password)

    assert [list(error["loc"]) for error in caught.value.errors()] == [location]
    login.count.assert_not_awaited()
