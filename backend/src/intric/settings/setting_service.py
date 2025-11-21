from typing import TYPE_CHECKING

from intric.ai_models.ai_models_service import AIModelsService
from intric.main.config import get_settings as get_app_settings
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permissions
from intric.settings.settings import SettingsPublic, SettingsUpsert
from intric.settings.settings_repo import SettingsRepository
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.feature_flag.feature_flag_service import FeatureFlagService

logger = get_logger(__name__)


class SettingService:
    def __init__(
        self,
        repo: SettingsRepository,
        user: UserInDB,
        ai_models_service: AIModelsService,
        feature_flag_service: "FeatureFlagService",
    ):
        self.repo = repo
        self.user = user
        self.ai_models_service = ai_models_service
        self.feature_flag_service = feature_flag_service

    async def get_settings(self):
        settings = await self.repo.get(self.user.id)

        # Populate using_templates from feature flag
        using_templates = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=self.user.tenant_id
        )

        # Get tenant_credentials_enabled from global config
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        # Handle case when user has no settings record yet
        if settings is None:
            return SettingsPublic(
                chatbot_widget={},
                using_templates=using_templates,
                tenant_credentials_enabled=tenant_credentials_enabled
            )

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget or {},
            using_templates=using_templates,
            tenant_credentials_enabled=tenant_credentials_enabled
        )

    async def update_settings(self, settings: SettingsPublic):
        settings_upsert = SettingsUpsert(**settings.model_dump(), user_id=self.user.id)

        settings_in_db = await self.repo.update(settings_upsert)
        logger.info(
            "Updated settings: %s for user: %s" % (settings_upsert, self.user.username)
        )

        return settings_in_db

    async def get_available_completion_models(self):
        return await self.ai_models_service.get_completion_models()

    async def get_available_embedding_models(self):
        return await self.ai_models_service.get_embedding_models()

    @validate_permissions(Permission.ADMIN)
    async def update_template_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the using_templates feature flag for tenant.

        **Admin Only:** Only users with admin permissions can toggle this setting.
        """
        logger.info(
            f"Admin user {self.user.username} toggling templates to {enabled} for tenant {self.user.tenant_id}"
        )

        # Get the feature flag
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(
            name="using_templates"
        )

        if not feature_flag:
            raise ValueError("using_templates feature flag not found")

        # Enable or disable for tenant
        if enabled:
            await self.feature_flag_service.enable_tenant(
                feature_id=feature_flag.feature_id,
                tenant_id=self.user.tenant_id
            )
        else:
            await self.feature_flag_service.disable_tenant(
                feature_id=feature_flag.feature_id,
                tenant_id=self.user.tenant_id
            )

        # Return updated settings with the known state (avoid read-after-write race)
        settings = await self.repo.get(self.user.id)

        logger.info(
            f"Templates successfully toggled to {enabled} for tenant {self.user.tenant_id}"
        )

        # Get tenant_credentials_enabled from global config
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget if settings else {},
            using_templates=enabled,  # Use the value we just set, not a re-query
            tenant_credentials_enabled=tenant_credentials_enabled
        )
