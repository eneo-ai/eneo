from typing import Annotated

from fastapi import Depends

from eneo.authentication.auth_dependencies import (
    get_user_from_token_or_assistant_api_key_without_assistant_id,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.dependencies.get_repository import get_repository
from eneo.settings.setting_service import SettingService
from eneo.settings.settings_repo import SettingsRepository
from eneo.users.user import UserInDB


def get_settings_service_allowing_read_only_key(
    user: Annotated[
        UserInDB,
        Depends(get_user_from_token_or_assistant_api_key_without_assistant_id),
    ],
    repo: Annotated[SettingsRepository, Depends(get_repository(SettingsRepository))],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> SettingService:
    return SettingService(
        repo=repo,
        user=user,
        ai_models_service=container.ai_models_service(),
        feature_flag_service=container.feature_flag_service(),
        tenant_repo=container.tenant_repo(),
        audit_service=container.audit_service(),
    )
