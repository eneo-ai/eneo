from typing import Annotated

from fastapi import Depends

from eneo.authentication.api_key_repo import ApiKeysRepository
from eneo.authentication.auth_service import AuthService
from eneo.server.dependencies.get_repository import get_repository


def get_auth_service(
    api_key_repo: Annotated[
        ApiKeysRepository, Depends(get_repository(ApiKeysRepository))
    ],
) -> AuthService:
    return AuthService(api_key_repo=api_key_repo)
