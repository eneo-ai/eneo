from typing import TYPE_CHECKING

from intric.ai_models.ai_models_service import AIModelsService
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.main.config import get_settings as get_app_settings
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permissions
from intric.settings.settings import SettingsPublic, SettingsUpsert
from intric.settings.settings_repo import SettingsRepository
from intric.tenants.tenant import TenantUpdate
from intric.tenants.tenant_repo import TenantRepository
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
        tenant_repo: TenantRepository,
        audit_service: AuditService,
    ):
        self.repo = repo
        self.user = user
        self.ai_models_service = ai_models_service
        self.feature_flag_service = feature_flag_service
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service

    async def get_settings(self):
        settings = await self.repo.get(self.user.id)

        # Populate using_templates from feature flag
        using_templates = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=self.user.tenant_id
        )

        # Populate audit_logging_enabled from feature flag
        audit_logging_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="audit_logging_enabled",
            tenant_id=self.user.tenant_id
        )

        # Get tenant_credentials_enabled from global config
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        # Populate api_key_scope_enforcement from feature flag
        api_key_scope_enforcement = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="api_key_scope_enforcement",
            tenant_id=self.user.tenant_id
        )

        # Get provisioning from tenant
        tenant = await self.tenant_repo.get(self.user.tenant_id)
        provisioning = tenant.provisioning if tenant else False

        # Handle case when user has no settings record yet
        if settings is None:
            return SettingsPublic(
                chatbot_widget={},
                using_templates=using_templates,
                audit_logging_enabled=audit_logging_enabled,
                tenant_credentials_enabled=tenant_credentials_enabled,
                provisioning=provisioning,
                api_key_scope_enforcement=api_key_scope_enforcement,
            )

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget or {},
            using_templates=using_templates,
            audit_logging_enabled=audit_logging_enabled,
            tenant_credentials_enabled=tenant_credentials_enabled,
            provisioning=provisioning,
            api_key_scope_enforcement=api_key_scope_enforcement,
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

        # Query real old value before toggling
        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates", tenant_id=self.user.tenant_id
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

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled using_templates to {enabled}",
            metadata={
                "setting": "using_templates",
                "changes": {"using_templates": {"old": old_enabled, "new": enabled}},
            },
        )

        # Get global config flags
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        # Get tenant for provisioning
        tenant = await self.tenant_repo.get(self.user.tenant_id)

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget if settings else {},
            using_templates=enabled,  # Use the value we just set, not a re-query
            audit_logging_enabled=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="audit_logging_enabled",
                tenant_id=self.user.tenant_id
            ),
            tenant_credentials_enabled=tenant_credentials_enabled,
            provisioning=tenant.provisioning if tenant else False,
            api_key_scope_enforcement=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_scope_enforcement",
                tenant_id=self.user.tenant_id
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def update_audit_logging_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the audit_logging_enabled feature flag for tenant.

        **Admin Only:** Only users with admin permissions can toggle this setting.
        Enables/disables all audit logging for the tenant globally.
        """
        logger.info(
            f"Admin user {self.user.username} toggling audit logging to {enabled} for tenant {self.user.tenant_id}"
        )

        # Query real old value before toggling
        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="audit_logging_enabled", tenant_id=self.user.tenant_id
        )

        # Get the feature flag
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(
            name="audit_logging_enabled"
        )

        if not feature_flag:
            raise ValueError("audit_logging_enabled feature flag not found")

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
            f"Audit logging successfully toggled to {enabled} for tenant {self.user.tenant_id}"
        )

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled audit_logging_enabled to {enabled}",
            metadata={
                "setting": "audit_logging_enabled",
                "changes": {"audit_logging_enabled": {"old": old_enabled, "new": enabled}},
            },
        )

        # Get tenant_credentials_enabled from global config
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        # Get tenant for provisioning
        tenant = await self.tenant_repo.get(self.user.tenant_id)

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget if settings else {},
            using_templates=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="using_templates",
                tenant_id=self.user.tenant_id
            ),
            audit_logging_enabled=enabled,  # Use the value we just set, not a re-query
            tenant_credentials_enabled=tenant_credentials_enabled,
            provisioning=tenant.provisioning if tenant else False,
            api_key_scope_enforcement=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_scope_enforcement",
                tenant_id=self.user.tenant_id
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def update_provisioning_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle JIT provisioning for tenant."""
        logger.info(
            f"Admin {self.user.username} toggling provisioning to {enabled} for tenant {self.user.tenant_id}"
        )

        # Query real old value before toggling
        tenant_before = await self.tenant_repo.get(self.user.tenant_id)
        old_enabled = tenant_before.provisioning if tenant_before else False

        tenant_update = TenantUpdate(
            id=self.user.tenant_id,
            provisioning=enabled,
        )
        await self.tenant_repo.update_tenant(tenant_update)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled provisioning to {enabled}",
            metadata={
                "setting": "provisioning",
                "changes": {"provisioning": {"old": old_enabled, "new": enabled}},
            },
        )

        settings = await self.repo.get(self.user.id)
        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget if settings else {},
            using_templates=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="using_templates",
                tenant_id=self.user.tenant_id
            ),
            audit_logging_enabled=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="audit_logging_enabled",
                tenant_id=self.user.tenant_id
            ),
            tenant_credentials_enabled=tenant_credentials_enabled,
            provisioning=enabled,  # Use the value we just set
            api_key_scope_enforcement=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_scope_enforcement",
                tenant_id=self.user.tenant_id
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def update_scope_enforcement_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the api_key_scope_enforcement feature flag for tenant.

        **Admin Only:** Only users with admin permissions can toggle this setting.
        """
        logger.info(
            f"Admin user {self.user.username} toggling scope enforcement to {enabled} "
            f"for tenant {self.user.tenant_id}"
        )

        # Query real old value before toggling
        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="api_key_scope_enforcement", tenant_id=self.user.tenant_id
        )

        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(
            name="api_key_scope_enforcement"
        )

        if not feature_flag:
            raise ValueError("api_key_scope_enforcement feature flag not found")

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

        settings = await self.repo.get(self.user.id)

        logger.info(
            f"Scope enforcement successfully toggled to {enabled} "
            f"for tenant {self.user.tenant_id}"
        )

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled api_key_scope_enforcement to {enabled}",
            metadata={
                "setting": "api_key_scope_enforcement",
                "changes": {"api_key_scope_enforcement": {"old": old_enabled, "new": enabled}},
            },
        )

        app_settings = get_app_settings()
        tenant_credentials_enabled = app_settings.tenant_credentials_enabled

        # Get tenant for provisioning
        tenant = await self.tenant_repo.get(self.user.tenant_id)

        return SettingsPublic(
            chatbot_widget=settings.chatbot_widget if settings else {},
            using_templates=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="using_templates",
                tenant_id=self.user.tenant_id
            ),
            audit_logging_enabled=await self.feature_flag_service.check_is_feature_enabled(
                feature_name="audit_logging_enabled",
                tenant_id=self.user.tenant_id
            ),
            tenant_credentials_enabled=tenant_credentials_enabled,
            provisioning=tenant.provisioning if tenant else False,
            api_key_scope_enforcement=enabled,  # Use the value we just set
        )
