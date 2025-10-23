from uuid import UUID

from fastapi import Depends, Request, Security

from intric.authentication.auth_factory import get_auth_service
from intric.authentication.auth_service import AuthService
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.server.dependencies.auth_definitions import OAUTH2_SCHEME
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB


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
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    return await user_service.authenticate(token, api_key)


async def get_current_active_user_with_quota(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
) -> UserInDB:
    user_service = container.user_service()
    return await user_service.authenticate(token, api_key, with_quota_used=True)


async def get_user_from_token_or_assistant_api_key(
    id: UUID,
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.authenticate_with_assistant_api_key(
        api_key, token, assistant_id=id
    )


async def get_user_from_token_or_assistant_api_key_without_assistant_id(
    token: str = Security(OAUTH2_SCHEME),
    api_key: str = Security(_get_api_key_from_header),
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.authenticate_with_assistant_api_key(api_key, token)


def get_api_key(hashed: bool = True):
    async def _get_api_key(
        api_key: str = Security(_get_api_key_from_header),
        auth_service: AuthService = Depends(get_auth_service),
    ):
        return await auth_service.get_api_key(api_key, hash_key=hashed)

    return _get_api_key
