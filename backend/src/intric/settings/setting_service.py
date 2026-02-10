from typing import TYPE_CHECKING

from intric.ai_models.ai_models_service import AIModelsService
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.main.config import get_settings as get_app_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permissions
from intric.settings.settings import SettingsInDB, SettingsPublic, SettingsUpsert
from intric.settings.settings_repo import SettingsRepository
from intric.tenants.tenant import TenantUpdate
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.feature_flag.feature_flag import FeatureFlag
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

    async def _require_feature_flag(self, name: str) -> "FeatureFlag":
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(
            name=name
        )
        if not feature_flag:
            raise ValueError(f"{name} feature flag not found")
        return feature_flag

    async def _set_feature_flag_for_tenant(self, *, name: str, enabled: bool) -> None:
        feature_flag = await self._require_feature_flag(name)
        if feature_flag.feature_id is None:
            raise ValueError(f"{name} feature flag is missing an id")

        if enabled:
            await self.feature_flag_service.enable_tenant(
                feature_id=feature_flag.feature_id,
                tenant_id=self.user.tenant_id,
            )
            return

        await self.feature_flag_service.disable_tenant(
            feature_id=feature_flag.feature_id,
            tenant_id=self.user.tenant_id,
        )

    async def _build_settings_public(
        self,
        *,
        settings_in_db: SettingsInDB | None = None,
        overrides: dict[str, bool] | None = None,
    ) -> SettingsPublic:
        if settings_in_db is None:
            settings_in_db = await self.repo.get(self.user.id)

        if overrides is None:
            overrides = {}

        using_templates = (
            overrides["using_templates"]
            if "using_templates" in overrides
            else await self.feature_flag_service.check_is_feature_enabled(
                feature_name="using_templates",
                tenant_id=self.user.tenant_id,
            )
        )

        audit_logging_enabled = (
            overrides["audit_logging_enabled"]
            if "audit_logging_enabled" in overrides
            else await self.feature_flag_service.check_is_feature_enabled(
                feature_name="audit_logging_enabled",
                tenant_id=self.user.tenant_id,
            )
        )

        api_key_scope_enforcement = (
            overrides["api_key_scope_enforcement"]
            if "api_key_scope_enforcement" in overrides
            else await self.feature_flag_service.check_is_feature_enabled_fail_closed(
                feature_name="api_key_scope_enforcement",
                tenant_id=self.user.tenant_id,
            )
        )

        api_key_strict_mode = (
            overrides["api_key_strict_mode"]
            if "api_key_strict_mode" in overrides
            else await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_strict_mode",
                tenant_id=self.user.tenant_id,
            )
        )

        tenant = await self.tenant_repo.get(self.user.tenant_id)
        provisioning = (
            overrides["provisioning"]
            if "provisioning" in overrides
            else tenant.provisioning if tenant else False
        )

        app_settings = get_app_settings()

        return SettingsPublic(
            chatbot_widget=(settings_in_db.chatbot_widget if settings_in_db else {}) or {},
            using_templates=using_templates,
            audit_logging_enabled=audit_logging_enabled,
            tenant_credentials_enabled=app_settings.tenant_credentials_enabled,
            provisioning=provisioning,
            api_key_scope_enforcement=api_key_scope_enforcement,
            api_key_strict_mode=api_key_strict_mode,
        )

    async def get_settings(self):
        settings = await self.repo.get(self.user.id)
        return await self._build_settings_public(settings_in_db=settings)

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
            "Admin user %s toggling templates to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=self.user.tenant_id,
        )
        await self._set_feature_flag_for_tenant(name="using_templates", enabled=enabled)

        settings = await self.repo.get(self.user.id)

        logger.info(
            "Templates successfully toggled to %s for tenant %s",
            enabled,
            self.user.tenant_id,
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

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"using_templates": enabled},
        )

    @validate_permissions(Permission.ADMIN)
    async def update_audit_logging_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the audit_logging_enabled feature flag for tenant.

        **Admin Only:** Only users with admin permissions can toggle this setting.
        Enables/disables all audit logging for the tenant globally.
        """
        logger.info(
            "Admin user %s toggling audit logging to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="audit_logging_enabled",
            tenant_id=self.user.tenant_id,
        )
        await self._set_feature_flag_for_tenant(
            name="audit_logging_enabled",
            enabled=enabled,
        )

        settings = await self.repo.get(self.user.id)

        logger.info(
            "Audit logging successfully toggled to %s for tenant %s",
            enabled,
            self.user.tenant_id,
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
                "changes": {
                    "audit_logging_enabled": {"old": old_enabled, "new": enabled}
                },
            },
        )

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"audit_logging_enabled": enabled},
        )

    @validate_permissions(Permission.ADMIN)
    async def update_provisioning_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle JIT provisioning for tenant."""
        logger.info(
            "Admin %s toggling provisioning to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

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
        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"provisioning": enabled},
        )

    @validate_permissions(Permission.ADMIN)
    async def update_scope_enforcement_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the api_key_scope_enforcement feature flag for tenant.

        **Admin Only:** Only users with admin permissions can toggle this setting.
        """
        logger.info(
            "Admin user %s toggling scope enforcement to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

        old_enabled = await self.feature_flag_service.check_is_feature_enabled_fail_closed(
            feature_name="api_key_scope_enforcement",
            tenant_id=self.user.tenant_id,
        )

        strict_was_enabled = False
        if not enabled:
            strict_was_enabled = await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_strict_mode",
                tenant_id=self.user.tenant_id,
            )

        await self._set_feature_flag_for_tenant(
            name="api_key_scope_enforcement",
            enabled=enabled,
        )
        if not enabled and strict_was_enabled:
            await self._set_feature_flag_for_tenant(
                name="api_key_strict_mode",
                enabled=False,
            )

        settings = await self.repo.get(self.user.id)

        logger.info(
            "Scope enforcement successfully toggled to %s for tenant %s",
            enabled,
            self.user.tenant_id,
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
                "changes": {
                    "api_key_scope_enforcement": {"old": old_enabled, "new": enabled}
                },
            },
        )

        overrides: dict[str, bool] = {"api_key_scope_enforcement": enabled}
        if not enabled and strict_was_enabled:
            overrides["api_key_strict_mode"] = False

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides=overrides,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_strict_mode_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the api_key_strict_mode feature flag for tenant."""
        logger.info(
            "Admin user %s toggling strict mode to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

        if enabled:
            scope_enforcement_enabled = (
                await self.feature_flag_service.check_is_feature_enabled_fail_closed(
                    feature_name="api_key_scope_enforcement",
                    tenant_id=self.user.tenant_id,
                )
            )
            if not scope_enforcement_enabled:
                raise BadRequestException(
                    "Strict mode requires scope enforcement to be enabled."
                )

        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="api_key_strict_mode",
            tenant_id=self.user.tenant_id,
        )
        await self._set_feature_flag_for_tenant(name="api_key_strict_mode", enabled=enabled)

        settings = await self.repo.get(self.user.id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled api_key_strict_mode to {enabled}",
            metadata={
                "setting": "api_key_strict_mode",
                "changes": {"api_key_strict_mode": {"old": old_enabled, "new": enabled}},
            },
        )

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"api_key_strict_mode": enabled},
        )
