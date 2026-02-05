from uuid import UUID

from typing import NoReturn

from fastapi import Depends, HTTPException, Request, Security, status

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.authentication.api_key_resolver import ApiKeyValidationError
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
    async def _dep(
        request: Request,
        user: UserInDB = Depends(get_current_active_user),
    ):
        key = getattr(request.state, "api_key", None)
        if key is None:
            return user
        ordering = {
            ApiKeyPermission.READ: 0,
            ApiKeyPermission.WRITE: 1,
            ApiKeyPermission.ADMIN: 2,
        }
        actual = ApiKeyPermission(key.permission)
        if ordering[actual] < ordering[required]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_permission",
                    "message": "API key does not have required permission.",
                },
            )
        return user

    return _dep
