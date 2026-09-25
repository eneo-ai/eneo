from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param

from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_router_helpers import raise_api_key_http_error
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.exceptions import AuthenticationException
from eneo.modules.module_auth import ModuleRequestPrincipal
from eneo.server.dependencies.container import get_container


async def authenticate_module_request(
    *,
    module_key: str,
    request: Request,
    container: Container,
) -> Container:
    """Authenticate both module credentials into one real-user container."""
    scheme, access_token = get_authorization_scheme_param(
        request.headers.get("Authorization")
    )
    if scheme.lower() != "bearer":
        access_token = None
    api_key_secret = request.headers.get(get_settings().api_key_header_name)
    if not access_token or not api_key_secret:
        raise AuthenticationException(
            "Module resources require both Bearer and API key credentials."
        )

    try:
        service_user = await container.user_service().authenticate(
            api_key=api_key_secret,
            request=request,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc, request=request)

    resolved_key = service_user.active_api_key
    if resolved_key is None:
        raise AuthenticationException("Module API key authentication failed.")

    principal = await container.module_auth_broker().authenticate_resource_request(
        module_key=module_key,
        access_token=access_token,
        api_key=resolved_key,
    )
    override_user(container=container, user=principal.user)
    request.state.module_principal = principal
    return container


async def get_module_request_container(
    module_key: str,
    request: Request,
    container: Annotated[Container, Depends(get_container())],
) -> Container:
    """Dynamic module-key dependency used by the broker validation route."""
    return await authenticate_module_request(
        module_key=module_key,
        request=request,
        container=container,
    )


def require_module_request(
    module_key: str,
) -> Callable[..., Awaitable[Container]]:
    """Bind dual authentication to a module-owned resource router.

    Future resource routers must use a server-owned constant here, for example
    ``Depends(require_module_request("speech-to-text"))``. The dynamic broker
    route exists for deployment diagnostics only and is not a substitute for
    enforcing this dependency on the resource operation itself.
    """

    async def _dependency(
        request: Request,
        container: Annotated[Container, Depends(get_container())],
    ) -> Container:
        return await authenticate_module_request(
            module_key=module_key,
            request=request,
            container=container,
        )

    return _dependency


def module_principal_from_request(request: Request) -> ModuleRequestPrincipal:
    principal = getattr(request.state, "module_principal", None)
    if not isinstance(principal, ModuleRequestPrincipal):
        raise RuntimeError("Module request dependency did not run.")
    return principal
