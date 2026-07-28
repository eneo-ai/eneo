from typing import TYPE_CHECKING
from uuid import UUID

from eneo.ai_models.ai_models_service import AIModelsService
from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.completion_models.domain.skill_context import skill_context_token_allowance
from eneo.main.config import get_settings as get_app_settings
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
)
from eneo.main.logging import get_logger
from eneo.object_content.runtime import ObjectContentRuntime, object_content_runtime
from eneo.roles.permissions import Permission, validate_permissions
from eneo.settings.settings import (
    SettingsBase,
    SettingsInDB,
    SettingsPublic,
    SettingsUpsert,
    SkillExecutionBlockState,
    SkillRuntimeModelProjection,
    SkillRuntimeModelProjections,
    SkillRuntimePolicyPublic,
    SkillRuntimePolicyUpdate,
)
from eneo.settings.settings_repo import SettingsRepository
from eneo.skills.domain.skill import (
    SKILL_RUNTIME_POLICY_DEFAULTS,
    Skill,
    SkillExecutionBlock,
    SkillRuntimePolicy,
    SkillRuntimePolicyChange,
    normalize_skill_execution_block_reason,
)
from eneo.skills.domain.skill_repo import SkillRepo
from eneo.tenants.tenant import TenantUpdate
from eneo.tenants.tenant_repo import TenantRepository
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.feature_flag.feature_flag import FeatureFlag
    from eneo.feature_flag.feature_flag_service import FeatureFlagService

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
        skill_repo: SkillRepo,
        object_content: ObjectContentRuntime = object_content_runtime,
    ):
        super().__init__()
        self.repo = repo
        self.user = user
        self.ai_models_service = ai_models_service
        self.feature_flag_service = feature_flag_service
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service
        self.skill_repo = skill_repo
        self.object_content = object_content

    async def _require_organization_skill(self, *, skill_id: UUID) -> Skill:
        skill = await self.skill_repo.get_organization_for_tenant(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        if skill is None:
            raise NotFoundException()
        return skill

    @staticmethod
    def _execution_block_audit_value(
        block: SkillExecutionBlock,
    ) -> dict[str, str]:
        return {
            "id": str(block.id),
            "skill_id": str(block.skill_id),
            "blocked_by_user_id": str(block.blocked_by_user_id),
            "reason": block.reason,
            "blocked_at": block.blocked_at.isoformat(),
        }

    @validate_permissions(Permission.ADMIN)
    async def get_skill_execution_block(
        self,
        *,
        skill_id: UUID,
    ) -> SkillExecutionBlockState:
        await self._require_organization_skill(skill_id=skill_id)
        block = await self.skill_repo.get_active_execution_block(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
        )
        return SkillExecutionBlockState.from_domain(
            skill_id=skill_id,
            block=block,
        )

    @validate_permissions(Permission.ADMIN)
    async def block_skill_execution(
        self,
        *,
        skill_id: UUID,
        reason: str,
    ) -> SkillExecutionBlockState:
        skill = await self._require_organization_skill(skill_id=skill_id)
        if skill.first_published_at is None:
            raise BadRequestException(
                "Only an organisation Skill that has been published can be blocked"
            )
        normalized_reason = normalize_skill_execution_block_reason(reason)
        change = await self.skill_repo.block_organization_skill(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
            blocked_by_user_id=self.user.id,
            reason=normalized_reason,
        )
        if change is None:
            raise NotFoundException()
        if change.changed:
            new_value = self._execution_block_audit_value(change.block)
            await self.audit_service.log_async(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.TENANT_SETTINGS_UPDATED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=self.user.tenant_id,
                description="Blocked organisation Skill execution",
                metadata={
                    "setting": "skill_execution_block",
                    "skill_id": str(skill_id),
                    "changes": {
                        "skill_execution_block": {
                            "old": None,
                            "new": new_value,
                        }
                    },
                    "reason": change.block.reason,
                    "changed_at": change.block.blocked_at.isoformat(),
                },
            )
        return SkillExecutionBlockState.from_domain(
            skill_id=skill_id,
            block=change.block,
        )

    @validate_permissions(Permission.ADMIN)
    async def unblock_skill_execution(
        self,
        *,
        skill_id: UUID,
        expected_block_id: UUID,
        reason: str,
    ) -> SkillExecutionBlockState:
        await self._require_organization_skill(skill_id=skill_id)
        normalized_reason = normalize_skill_execution_block_reason(reason)
        change = await self.skill_repo.unblock_organization_skill(
            tenant_id=self.user.tenant_id,
            skill_id=skill_id,
            expected_block_id=expected_block_id,
            unblocked_by_user_id=self.user.id,
            reason=normalized_reason,
        )
        if change is None:
            raise NotFoundException()
        if change.block.unblocked_at is None:
            raise RuntimeError("Released Skill execution block is still active")
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Unblocked organisation Skill execution",
            metadata={
                "setting": "skill_execution_block",
                "skill_id": str(skill_id),
                "changes": {
                    "skill_execution_block": {
                        "old": self._execution_block_audit_value(change.block),
                        "new": None,
                    }
                },
                "reason": change.block.unblock_reason,
                "changed_at": change.block.unblocked_at.isoformat(),
            },
        )
        return SkillExecutionBlockState(
            skill_id=skill_id,
            block=None,
        )

    @staticmethod
    def _runtime_policy_audit_changes(
        change: SkillRuntimePolicyChange,
    ) -> dict[str, dict[str, bool | int]]:
        old, new = change.old, change.new
        changes: dict[str, dict[str, bool | int]] = {}
        if old.selective_activation_enabled != new.selective_activation_enabled:
            changes["selective_activation_enabled"] = {
                "old": old.selective_activation_enabled,
                "new": new.selective_activation_enabled,
            }
        if old.max_attached_skills != new.max_attached_skills:
            changes["max_attached_skills"] = {
                "old": old.max_attached_skills,
                "new": new.max_attached_skills,
            }
        if old.context_share_percent != new.context_share_percent:
            changes["context_share_percent"] = {
                "old": old.context_share_percent,
                "new": new.context_share_percent,
            }
        if old.max_activations_per_turn != new.max_activations_per_turn:
            changes["max_activations_per_turn"] = {
                "old": old.max_activations_per_turn,
                "new": new.max_activations_per_turn,
            }
        return changes

    @validate_permissions(Permission.ADMIN)
    async def get_skill_runtime_policy(self) -> SkillRuntimePolicyPublic:
        policy = await self.skill_repo.get_or_seed_runtime_policy(
            tenant_id=self.user.tenant_id
        )
        return SkillRuntimePolicyPublic.from_domain(policy)

    async def _apply_skill_runtime_policy(
        self,
        *,
        policy: SkillRuntimePolicy,
        description: str,
    ) -> SkillRuntimePolicyPublic:
        change = await self.skill_repo.update_runtime_policy(
            tenant_id=self.user.tenant_id,
            policy=policy,
        )
        if change.changed:
            await self.audit_service.log_async(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.TENANT_SETTINGS_UPDATED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=self.user.tenant_id,
                description=description,
                metadata={
                    "setting": "skill_runtime_policy",
                    "changes": self._runtime_policy_audit_changes(change),
                },
            )
        return SkillRuntimePolicyPublic.from_domain(change.new)

    @validate_permissions(Permission.ADMIN)
    async def update_skill_runtime_policy(
        self, update: SkillRuntimePolicyUpdate
    ) -> SkillRuntimePolicyPublic:
        return await self._apply_skill_runtime_policy(
            policy=update.to_domain(),
            description="Updated the Skill runtime policy",
        )

    @validate_permissions(Permission.ADMIN)
    async def reset_skill_runtime_policy(self) -> SkillRuntimePolicyPublic:
        return await self._apply_skill_runtime_policy(
            policy=SKILL_RUNTIME_POLICY_DEFAULTS,
            description="Restored the seeded Skill runtime policy defaults",
        )

    @validate_permissions(Permission.ADMIN)
    async def get_skill_runtime_model_projections(
        self,
    ) -> SkillRuntimeModelProjections:
        policy = await self.skill_repo.get_or_seed_runtime_policy(
            tenant_id=self.user.tenant_id
        )
        models = await self.ai_models_service.get_completion_models()
        return SkillRuntimeModelProjections(
            context_share_percent=policy.context_share_percent,
            models=[
                SkillRuntimeModelProjection(
                    completion_model_id=model.id,
                    name=model.name,
                    nickname=model.nickname,
                    max_input_tokens=model.max_input_tokens,
                    supports_tool_calling=model.supports_tool_calling,
                    skill_context_token_allowance=skill_context_token_allowance(
                        max_input_tokens=model.max_input_tokens,
                        context_share_percent=policy.context_share_percent,
                    ),
                )
                for model in models
                if model.can_access
            ],
        )

    async def _require_feature_flag(self, name: str) -> "FeatureFlag":
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(  # type: ignore[reportUnknownMemberType]  # feature_flag_repo.one_or_none uses **filters which lacks type annotations
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

        api_key_expiry_notifications = (
            overrides["api_key_expiry_notifications"]
            if "api_key_expiry_notifications" in overrides
            else await self.feature_flag_service.check_is_feature_enabled(
                feature_name="api_key_expiry_notifications",
                tenant_id=self.user.tenant_id,
            )
        )

        tenant = await self.tenant_repo.get(self.user.tenant_id)
        provisioning = (
            overrides["provisioning"]
            if "provisioning" in overrides
            else tenant.provisioning
            if tenant
            else False
        )

        app_settings = get_app_settings()

        return SettingsPublic(
            chatbot_widget=(settings_in_db.chatbot_widget if settings_in_db else {})
            or {},
            object_content_enabled=self.object_content.enabled,
            using_templates=using_templates,
            audit_logging_enabled=audit_logging_enabled,
            tenant_credentials_enabled=app_settings.tenant_credentials_enabled,
            provisioning=provisioning,
            api_key_expiry_notifications=api_key_expiry_notifications,
        )

    async def get_settings(self) -> SettingsPublic:
        settings = await self.repo.get(self.user.id)
        return await self._build_settings_public(settings_in_db=settings)

    async def update_settings(self, settings: SettingsBase) -> SettingsPublic:
        settings_upsert = SettingsUpsert(**settings.model_dump(), user_id=self.user.id)

        existing_settings = await self.repo.get(self.user.id)
        if existing_settings is None:
            settings_in_db = await self.repo.add(settings_upsert)
        else:
            settings_in_db = await self.repo.update(settings_upsert)
        logger.info(
            "Updated settings: %s for user: %s" % (settings_upsert, self.user.username)
        )

        return await self._build_settings_public(settings_in_db=settings_in_db)

    async def get_available_completion_models(self) -> list[CompletionModelPublic]:
        return await self.ai_models_service.get_completion_models()

    async def get_available_embedding_models(
        self,
    ) -> list[EmbeddingModelPublicLegacy]:
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
            user=self.user,
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
            user=self.user,
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
            user=self.user,
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
    async def update_api_key_expiry_notifications_setting(
        self, enabled: bool
    ) -> SettingsPublic:
        """Toggle API key expiry notifications for tenant."""
        logger.info(
            "Admin user %s toggling API key expiry notifications to %s for tenant %s",
            self.user.username,
            enabled,
            self.user.tenant_id,
        )

        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="api_key_expiry_notifications",
            tenant_id=self.user.tenant_id,
        )
        await self._set_feature_flag_for_tenant(
            name="api_key_expiry_notifications",
            enabled=enabled,
        )

        settings = await self.repo.get(self.user.id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled api_key_expiry_notifications to {enabled}",
            metadata={
                "setting": "api_key_expiry_notifications",
                "changes": {
                    "api_key_expiry_notifications": {
                        "old": old_enabled,
                        "new": enabled,
                    }
                },
            },
        )

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"api_key_expiry_notifications": enabled},
        )
