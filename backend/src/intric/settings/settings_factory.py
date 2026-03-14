from fastapi import Depends

from intric.authentication.auth_dependencies import (
    get_user_from_token_or_assistant_api_key_without_assistant_id,
)
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.dependencies.get_repository import get_repository
from intric.settings.setting_service import SettingService
from intric.settings.settings_repo import SettingsRepository
from intric.users.user import UserInDB


def get_settings_service_allowing_read_only_key(
    user: UserInDB = Depends(
        get_user_from_token_or_assistant_api_key_without_assistant_id
    ),
    repo: SettingsRepository = Depends(get_repository(SettingsRepository)),
    container: Container = Depends(get_container(with_user=True)),
):
    return SettingService(
        repo=repo,
        user=user,
        ai_models_service=container.ai_models_service(),
        feature_flag_service=container.feature_flag_service(),
        tenant_repo=container.tenant_repo(),
        audit_service=container.audit_service(),
    )
