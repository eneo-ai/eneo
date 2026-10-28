from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.requests import Request

from eneo.main.config import get_settings, set_settings
from eneo.main.exceptions import AuthenticationException
from eneo.modules.module_auth import ModuleRequestPrincipal
from eneo.server.dependencies.module_auth import authenticate_module_request

# A same-origin browser session cookie never stands in for either module
# credential: both still come from the headers.
SESSION_COOKIE = [
    (b"cookie", b"__Host-eneo_web=session-cookie; eneo_web=session-cookie"),
    (b"sec-fetch-site", b"same-origin"),
]


@pytest.fixture(autouse=True)
def browser_session_enabled():
    original = get_settings()
    set_settings(original.model_copy(update={"browser_session_enabled": True}))
    yield
    set_settings(original)


def make_request(
    *,
    authorization: str | None,
    api_key: str | None,
    extra: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = list(extra or [])
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    if api_key is not None:
        headers.append(
            (get_settings().api_key_header_name.lower().encode(), api_key.encode())
        )
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.parametrize("extra", [None, SESSION_COOKIE])
async def test_module_dependency_resolves_service_key_and_module_token_together(
    extra,
):
    request = make_request(
        authorization="Bearer module-user-token",
        api_key="sk_module-service-key",
        extra=extra,
    )
    resolved_key = MagicMock(id=uuid4())
    service_user = MagicMock(active_api_key=resolved_key)
    real_user = MagicMock(id=uuid4())
    principal = ModuleRequestPrincipal(
        module=MagicMock(),
        user=real_user,
        api_key=resolved_key,
        access_token="module-user-token",
    )
    user_service = AsyncMock()
    user_service.authenticate.return_value = service_user
    broker = AsyncMock()
    broker.authenticate_resource_request.return_value = principal
    container = MagicMock()
    container.user_service.return_value = user_service
    container.module_auth_broker.return_value = broker

    with patch("eneo.server.dependencies.module_auth.override_user") as override_user:
        result = await authenticate_module_request(
            module_key="speech-to-text",
            request=request,
            container=container,
        )

    assert result is container
    user_service.authenticate.assert_awaited_once_with(
        api_key="sk_module-service-key",
        request=request,
    )
    broker.authenticate_resource_request.assert_awaited_once_with(
        module_key="speech-to-text",
        access_token="module-user-token",
        api_key=resolved_key,
    )
    override_user.assert_called_once_with(container=container, user=real_user)
    assert request.state.module_principal is principal


@pytest.mark.parametrize("extra", [None, SESSION_COOKIE])
@pytest.mark.parametrize(
    ("authorization", "api_key"),
    [
        (None, "sk_module-service-key"),
        ("Basic credentials", "sk_module-service-key"),
        ("Bearer module-user-token", None),
    ],
)
async def test_module_dependency_requires_both_credentials(
    authorization, api_key, extra
):
    container = MagicMock()

    with pytest.raises(AuthenticationException, match="both Bearer and API key"):
        await authenticate_module_request(
            module_key="speech-to-text",
            request=make_request(
                authorization=authorization, api_key=api_key, extra=extra
            ),
            container=container,
        )

    container.user_service.assert_not_called()
