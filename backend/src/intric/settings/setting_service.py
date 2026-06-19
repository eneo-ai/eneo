from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from intric.ai_models.ai_models_service import AIModelsService
from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.ai_builder.ai_builder_settings import (
    apply_ai_builder_budget_policy_patch,
    resolve_ai_builder_budget_policy,
)
from intric.flows.flow_document_limits import (
    apply_flow_document_render_limits_patch,
    resolve_flow_document_render_limits,
)
from intric.flows.flow_evidence_policy import (
    apply_flow_evidence_policy_patch,
    resolve_flow_evidence_policy,
)
from intric.flows.flow_input_limits import (
    FlowInputLimits,
    apply_flow_input_limits_patch,
    resolve_flow_input_limits,
)
from intric.flows.flow_retention_policy import (
    apply_flow_retention_policy_patch,
    resolve_flow_retention_policy,
)
from intric.flows.flow_runtime_policy import (
    apply_flow_runtime_policy_patch,
    resolve_flow_runtime_policy,
)
from intric.flows.flow_settings import normalize_flow_settings_object
from intric.main.config import get_settings as get_app_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permissions
from intric.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowDocumentRenderLimitsPublic,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    FlowRuntimePolicyPublic,
    FlowRuntimePolicyUpdate,
    SettingsInDB,
    SettingsPublic,
    SettingsUpsert,
)
from intric.settings.settings_repo import SettingsRepository
from intric.tenants.tenant import TenantUpdate
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.feature_flag.feature_flag import FeatureFlag
    from intric.feature_flag.feature_flag_service import FeatureFlagService

logger = get_logger(__name__)

FLOW_SETTINGS_INVALID_PAYLOAD_CODE = "flow_settings_invalid_payload"


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
        super().__init__()
        self.repo = repo
        self.user = user
        self.ai_models_service = ai_models_service
        self.feature_flag_service = feature_flag_service
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service

    async def _require_feature_flag(self, name: str) -> "FeatureFlag":
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(  # type: ignore[reportUnknownMemberType]  # feature_flag_repo.one_or_none uses **filters which lacks type annotations
            name=name
        )
        if not feature_flag:
            raise ValueError(f"{name} feature flag not found")
        return feature_flag

    async def _set_feature_flag_for_tenant(self, *, name: str, enabled: bool) -> None:
        feature_flag = await self.feature_flag_service.feature_flag_repo.one_or_none(
            name=name
        )
        if feature_flag is None:
            feature_flag = await self.feature_flag_service.create_feature_flag(
                name=name
            )
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
            using_templates=using_templates,
            audit_logging_enabled=audit_logging_enabled,
            tenant_credentials_enabled=app_settings.tenant_credentials_enabled,
            provisioning=provisioning,
            api_key_expiry_notifications=api_key_expiry_notifications,
        )

    async def get_settings(self) -> SettingsPublic:
        settings = await self.repo.get(self.user.id)
        return await self._build_settings_public(settings_in_db=settings)

    async def update_settings(self, settings: SettingsPublic) -> SettingsInDB:
        settings_upsert = SettingsUpsert(**settings.model_dump(), user_id=self.user.id)

        settings_in_db = await self.repo.update(settings_upsert)
        logger.info(
            "Updated settings: %s for user: %s" % (settings_upsert, self.user.username)
        )

        return settings_in_db

    async def _get_tenant_for_flow_settings(self) -> Any:
        tenant_override = getattr(self.tenant_repo, "tenant", None)
        if tenant_override is not None:
            return tenant_override
        return await self.tenant_repo.get(self.user.tenant_id)

    async def _persist_flow_settings(self, flow_settings: dict[str, Any]) -> None:
        normalized_flow_settings = normalize_flow_settings_object(flow_settings)
        tenant_update = TenantUpdate(
            id=self.user.tenant_id,
            flow_settings=normalized_flow_settings,
        )
        update_tenant = getattr(self.tenant_repo, "update_tenant", None)
        if callable(update_tenant):
            await cast(Callable[[TenantUpdate], Awaitable[Any]], update_tenant)(
                tenant_update
            )
            return
        tenant = await self._get_tenant_for_flow_settings()
        next_tenant = tenant.model_copy(
            update={"flow_settings": normalized_flow_settings}
        )
        setattr(self.tenant_repo, "tenant", next_tenant)

        async def _get_updated_tenant(_tenant_id: Any) -> Any:
            return getattr(self.tenant_repo, "tenant")

        setattr(self.tenant_repo, "get", _get_updated_tenant)

    async def get_flow_input_limits_resolved(self) -> FlowInputLimits:
        tenant = await self._get_tenant_for_flow_settings()
        return resolve_flow_input_limits(getattr(tenant, "flow_settings", None))

    @validate_permissions(Permission.ADMIN)
    async def get_flow_input_limits(self) -> FlowInputLimitsPublic:
        limits = await self.get_flow_input_limits_resolved()
        return FlowInputLimitsPublic(
            file_max_size_bytes=limits.file_max_size_bytes,
            audio_max_size_bytes=limits.audio_max_size_bytes,
            max_files_per_run=limits.max_files_per_run,
            audio_max_files_per_run=limits.audio_max_files_per_run,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_flow_input_limits(
        self,
        payload: FlowInputLimitsUpdate,
    ) -> FlowInputLimitsPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one flow input limit field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        previous = await self.get_flow_input_limits()
        remove_keys = {key for key, value in patch.items() if value is None}
        updated_values = {
            key: value for key, value in patch.items() if value is not None
        }
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_input_limits_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            remove_keys=remove_keys,
            **updated_values,
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_flow_input_limits()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow input limits",
            metadata={
                "setting": "flow_input_limits",
                "changes": {
                    key: {
                        "old": getattr(previous, key),
                        "new": getattr(updated, key),
                    }
                    for key in patch
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_flow_document_render_limits(
        self,
    ) -> FlowDocumentRenderLimitsPublic:
        tenant = await self._get_tenant_for_flow_settings()
        limits = resolve_flow_document_render_limits(
            getattr(tenant, "flow_settings", None)
        )
        return FlowDocumentRenderLimitsPublic.from_domain(limits)

    @validate_permissions(Permission.ADMIN)
    async def update_flow_document_render_limits(
        self,
        payload: FlowDocumentRenderLimitsUpdate,
    ) -> FlowDocumentRenderLimitsPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one flow document render limit field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        previous = await self.get_flow_document_render_limits()
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_document_render_limits_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            remove_keys={key for key, value in patch.items() if value is None},
            **{key: value for key, value in patch.items() if value is not None},
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_flow_document_render_limits()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow document render limits",
            metadata={
                "setting": "flow_document_render_limits",
                "changes": {
                    key: {
                        "old": getattr(previous, key),
                        "new": getattr(updated, key),
                    }
                    for key in patch
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_flow_runtime_policy(self) -> FlowRuntimePolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        policy = resolve_flow_runtime_policy(getattr(tenant, "flow_settings", None))
        return FlowRuntimePolicyPublic(
            default_step_timeout_seconds=policy.default_step_timeout_seconds,
            max_step_timeout_seconds=policy.max_step_timeout_seconds,
            hard_ceiling_seconds=policy.hard_ceiling_seconds,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_flow_runtime_policy(
        self,
        payload: FlowRuntimePolicyUpdate,
    ) -> FlowRuntimePolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one flow runtime policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        previous = await self.get_flow_runtime_policy()
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_runtime_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            remove_keys={key for key, value in patch.items() if value is None},
            **{key: value for key, value in patch.items() if value is not None},
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_flow_runtime_policy()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow runtime policy",
            metadata={
                "setting": "flow_runtime_policy",
                "changes": {
                    key: {
                        "old": getattr(previous, key),
                        "new": getattr(updated, key),
                    }
                    for key in patch
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_ai_builder_budget_settings(self) -> AIBuilderBudgetSettingsPublic:
        tenant = await self._get_tenant_for_flow_settings()
        policy = resolve_ai_builder_budget_policy(
            getattr(tenant, "flow_settings", None)
        )
        return AIBuilderBudgetSettingsPublic(
            conversation_safety_buffer_tokens=policy.conversation_safety_buffer_tokens,
            minimum_conversation_budget_tokens=policy.minimum_conversation_budget_tokens,
            unknown_model_context_window_tokens=policy.unknown_model_context_window_tokens,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_ai_builder_budget_settings(
        self,
        payload: AIBuilderBudgetSettingsUpdate,
    ) -> AIBuilderBudgetSettingsPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one AI Builder budget field must be provided."
            )
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_ai_builder_budget_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            **patch,
            remove_keys={key for key, value in patch.items() if value is None},
        )
        await self._persist_flow_settings(next_flow_settings)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated AI Builder budget settings",
            metadata={"setting": "ai_builder_budget_settings", "changes": patch},
        )
        return await self.get_ai_builder_budget_settings()

    @validate_permissions(Permission.ADMIN)
    async def get_flow_evidence_policy(self) -> FlowEvidencePolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        policy = resolve_flow_evidence_policy(getattr(tenant, "flow_settings", None))
        return FlowEvidencePolicyPublic(
            allow_sensitive_flow_exports=policy.allow_sensitive_flow_exports,
            allow_space_admin_raw_export_class3=policy.allow_space_admin_raw_export_class3,
            allow_run_owner_raw_export_class3=policy.allow_run_owner_raw_export_class3,
            allow_service_key_raw_export_class3=policy.allow_service_key_raw_export_class3,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_flow_evidence_policy(
        self,
        payload: FlowEvidencePolicyUpdate,
    ) -> FlowEvidencePolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one flow evidence policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_evidence_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            **patch,
        )
        await self._persist_flow_settings(next_flow_settings)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow evidence policy",
            metadata={"setting": "flow_evidence_policy", "changes": patch},
        )
        return await self.get_flow_evidence_policy()

    @validate_permissions(Permission.ADMIN)
    async def get_flow_retention_policy(self) -> FlowRetentionPolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        policy = resolve_flow_retention_policy(getattr(tenant, "flow_settings", None))
        return FlowRetentionPolicyPublic(
            run_debug_evidence_days=policy.run_debug_evidence_days,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_flow_retention_policy(
        self,
        payload: FlowRetentionPolicyUpdate,
    ) -> FlowRetentionPolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one flow retention policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        tenant = await self._get_tenant_for_flow_settings()
        try:
            next_flow_settings = apply_flow_retention_policy_patch(
                cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
                **patch,
                remove_keys={key for key, value in patch.items() if value is None},
            )
        except ValueError as error:
            raise BadRequestException(
                str(error),
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            ) from error
        await self._persist_flow_settings(next_flow_settings)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow retention policy",
            metadata={"setting": "flow_retention_policy", "changes": patch},
        )
        return await self.get_flow_retention_policy()

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
