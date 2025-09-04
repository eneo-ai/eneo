from uuid import UUID

from fastapi import Depends, Security, HTTPException, status

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.auth_definitions import API_KEY_HEADER, OAUTH2_SCHEME
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB
from intric.roles.permissions import Permission, validate_permission
from intric.main.exceptions import UnauthorizedException

logger = get_logger(__name__)


async def get_current_active_user(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(API_KEY_HEADER),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    return await user_service.authenticate(token, api_key)


async def get_current_active_user_with_quota(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(API_KEY_HEADER),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    return await user_service.authenticate(token, api_key, with_quota_used=True)


async def get_user_from_token_or_assistant_api_key(
    id: UUID,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(API_KEY_HEADER),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.authenticate_with_assistant_api_key(
        api_key, token, assistant_id=id
    )


async def get_user_from_token_or_assistant_api_key_without_assistant_id(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(API_KEY_HEADER),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.authenticate_with_assistant_api_key(api_key, token)


def get_api_key(hashed: bool = True):
    async def _get_api_key(
        api_key: str = Security(API_KEY_HEADER),
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