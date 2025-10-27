from typing import TYPE_CHECKING

from intric.ai_models.ai_models_service import AIModelsService
from intric.main.logging import get_logger
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

        # Handle case when user has no settings record yet
        if settings is None:
            return SettingsPublic(
                chatbot_widget={},
                using_templates=using_templates
            )

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget or {},
            using_templates=using_templates
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

    async def update_template_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the using_templates feature flag for tenant."""
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

        # Return updated settings
        return await self.get_settings()
