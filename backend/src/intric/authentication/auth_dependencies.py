from uuid import UUID

from typing import NoReturn

from fastapi import Depends, HTTPException, Request, Security, status

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.authentication.api_key_resolver import ApiKeyValidationError, check_resource_permission
from intric.authentication.auth_models import ApiKeyPermission
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.server.dependencies.auth_definitions import OAUTH2_SCHEME
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB
from intric.roles.permissions import Permission, validate_permission
from intric.main.exceptions import UnauthorizedException
from intric.main.logging import get_logger

logger = get_logger(__name__)


def _raise_api_key_http_error(exc: ApiKeyValidationError) -> NoReturn:
    logger.warning(
        "API key authentication failed",
        extra={"code": exc.code, "error_message": exc.message},
    )
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=exc.headers,
    ) from exc


async def _get_api_key_from_header(
    request: Request,
) -> str | None:
    """
    Dynamically get API key from the header specified in settings.
    """
    header_name = get_settings().api_key_header_name

    # Get the API key from the dynamically determined header
    api_key = request.headers.get(header_name)

    return api_key


async def get_current_active_user(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    try:
        return await user_service.authenticate(token, api_key, request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


async def get_current_active_user_with_quota(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    try:
        return await user_service.authenticate(
            token, api_key, with_quota_used=True, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


async def get_user_from_token_or_assistant_api_key(
    id: UUID,
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    try:
        return await user_service.authenticate_with_assistant_api_key(
            api_key, token, assistant_id=id, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


async def get_user_from_token_or_assistant_api_key_without_assistant_id(
    request: Request,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    try:
        return await user_service.authenticate_with_assistant_api_key(
            api_key, token, request=request
        )
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


def get_api_key(hashed: bool = True):
    async def _get_api_key(
        api_key: str = Security(_get_api_key_from_header),
        auth_service: AuthService = Depends(get_auth_service),
    ):
        return await auth_service.get_api_key(api_key, hash_key=hashed)

    return _get_api_key


def require_permission(permission: Permission):
    async def _dep(user: UserInDB = Depends(get_current_active_user)):
        try:
            validate_permission(user, permission)
        except UnauthorizedException as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    return _dep


def get_api_key_context(request: Request):
    return getattr(request.state, "api_key", None)


def require_api_key_permission(required: ApiKeyPermission):
    """Endpoint-level guard: stash required API key permission for post-auth check.

    Like ``require_resource_permission_for_method``, this dependency runs
    BEFORE authentication sets ``request.state.api_key``.  It stores the
    required permission level on ``request.state``, and the actual enforcement
    happens inside ``_resolve_api_key`` (user_service) after authentication.

    Bearer-token requests are unaffected — no API key state means no check.
    NOT gated by the feature flag — management guards always enforce.
    """

    async def _dep(request: Request) -> None:
        request.state._required_api_key_permission = required.value

    return _dep


ASSISTANTS_READ_OVERRIDES: frozenset[str] = frozenset({
    "estimate_tokens",
    "ask_assistant",
    "ask_followup",
    "leave_feedback",
})
KNOWLEDGE_READ_OVERRIDES: frozenset[str] = frozenset({"run_semantic_search"})

CONVERSATIONS_READ_OVERRIDES: frozenset[str] = frozenset({
    "chat",
    "leave_feedback",
})

APPS_READ_OVERRIDES: frozenset[str] = frozenset({
    "run_service",
    "run_app",
})


def require_resource_permission_for_method(
    resource_type: str,
    read_override_endpoints: frozenset[str] | None = None,
):
    """Router-level dependency: stores method→permission config for post-auth check.

    The actual permission check runs in ``_resolve_api_key`` (user_service)
    after authentication has set ``request.state.api_key``.  Router-level
    dependencies execute *before* route-level ``Depends()``, so we cannot
    inspect ``request.state.api_key`` here.
    """

    async def _dep(request: Request) -> None:
        request.state._resource_perm_config = {
            "resource_type": resource_type,
            "read_override_endpoints": read_override_endpoints,
        }

    return _dep


def require_resource_permission(resource_type: str, required: str):
    """Dependency factory for fine-grained per-resource permission checks.

    Fail-closed: if an API key header is present but request.state.api_key
    was not set by the auth dependency, raise 500 to surface a dependency
    ordering misconfiguration rather than silently allowing the request.
    """

    async def _dep(request: Request) -> None:
        key = getattr(request.state, "api_key", None)
        if key is None:
            # Check if an API key header was provided but auth didn't run
            header_name = get_settings().api_key_header_name
            if request.headers.get(header_name):
                logger.error(
                    "API key header present but request.state.api_key missing — "
                    "auth dependency may not have run before resource permission guard",
                    extra={"resource_type": resource_type, "required": required},
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "server_configuration_error",
                        "message": "Authentication state missing.",
                    },
                )
            return
        try:
            check_resource_permission(key, resource_type, required)
        except ApiKeyValidationError as exc:
            _raise_api_key_http_error(exc)

    return _dep
