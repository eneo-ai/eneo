from uuid import UUID

from fastapi import Depends, Header, Security

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.auth_definitions import API_KEY_HEADER, OAUTH2_SCHEME
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB

logger = get_logger(__name__)


async def _get_api_key_from_header(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    example: str | None = Header(None),
) -> str | None:
    """Dynamically get API key from the correct header based on settings."""
    header_name = get_settings().api_key_header_name
    logger.debug(f"Looking for API key in header: {header_name}")
    if header_name == "X-API-Key":
        logger.debug(f"Using X-API-Key header: {bool(x_api_key)}")
        return x_api_key
    elif header_name == "example":
        logger.debug(f"Using example header: {bool(example)}")
        return example
    # Fallback: try both
    return x_api_key or example


async def get_current_active_user(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Depends(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    logger.debug(f"get_current_active_user called - token: {bool(token)}, api_key: {bool(api_key)}")
    user_service = container.user_service()
    result = await user_service.authenticate(token, api_key)
    logger.debug(f"Authentication result: {result.email if result else 'None'}")
    return result


async def get_current_active_user_with_quota(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Depends(_get_api_key_from_header),
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
