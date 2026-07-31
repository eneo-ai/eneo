from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from eneo.ai_models.ai_models_service import AIModelsService
from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.completion_models.domain.skill_context import skill_context_token_allowance
from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionBoolPatch,
    FlowRetentionChangeConfirmation,
    FlowRetentionOrganizationProposal,
    FlowRetentionValuePatch,
)
from eneo.files.docx_template_validation import (
    MAX_TEMPLATE_ARCHIVE_ENTRIES,
    MAX_TEMPLATE_UNCOMPRESSED_BYTES,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    apply_ai_builder_budget_policy_patch,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.ai_builder.planning_state import PLANNING_STATE_PAYLOAD_CAP_BYTES
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    apply_flow_mapped_execution_policy_patch,
    resolve_flow_mapped_execution_policy,
)
from eneo.flows.domain.rag_evidence_policy import (
    apply_flow_rag_evidence_policy_patch,
    resolve_flow_rag_evidence_policy,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_BUDGET_MAX_TOKENS,
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
)
from eneo.flows.flow_document_limits import (
    apply_flow_document_render_limits_patch,
    resolve_flow_document_render_limits,
)
from eneo.flows.flow_evidence_policy import (
    apply_flow_evidence_policy_patch,
    resolve_flow_evidence_policy,
)
from eneo.flows.flow_input_limits import (
    FlowInputLimits,
    apply_flow_input_limits_patch,
    resolve_flow_input_limits,
)
from eneo.flows.flow_retention_policy import (
    apply_flow_retention_policy_patch,
    resolve_flow_retention_policy,
)
from eneo.flows.flow_runtime_policy import (
    apply_flow_runtime_policy_patch,
    resolve_flow_runtime_policy,
)
from eneo.flows.flow_settings import normalize_flow_settings_object
from eneo.main.config import get_settings as get_app_settings
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
)
from eneo.main.logging import get_logger
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.object_content.runtime import ObjectContentRuntime, object_content_runtime
from eneo.roles.permissions import Permission, validate_permissions
from eneo.settings.settings import (
    AIBuilderBudgetSettingsPublic,
    AIBuilderBudgetSettingsUpdate,
    FlowDocumentRenderLimitsPublic,
    FlowDocumentRenderLimitsUpdate,
    FlowEvidencePolicyPublic,
    FlowEvidencePolicyUpdate,
    FlowInputLimitsPublic,
    FlowInputLimitsUpdate,
    FlowMappedExecutionPolicyPublic,
    FlowMappedExecutionPolicyUpdate,
    FlowRagEvidencePolicyPublic,
    FlowRagEvidencePolicyUpdate,
    FlowRetentionEffectiveStatePublic,
    FlowRetentionImpactPreviewPublic,
    FlowRetentionOrganizationPreviewRequest,
    FlowRetentionPolicyPublic,
    FlowRetentionPolicyUpdate,
    FlowRuntimePolicyPublic,
    FlowRuntimePolicyUpdate,
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
        data_retention_service: DataRetentionService,
        skill_repo: SkillRepo,
        upload_admission: UploadAdmissionSnapshot | None = None,
        object_content: ObjectContentRuntime = object_content_runtime,
    ):
        super().__init__()
        self.repo = repo
        self.user = user
        self.ai_models_service = ai_models_service
        self.feature_flag_service = feature_flag_service
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service
        self.data_retention_service = data_retention_service
        self.skill_repo = skill_repo
        self.upload_admission = upload_admission
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
        return resolve_flow_input_limits(
            getattr(tenant, "flow_settings", None),
            defaults=self._require_upload_admission(),
        )

    def _require_upload_admission(self) -> UploadAdmissionSnapshot:
        if self.upload_admission is None:
            raise RuntimeError("Flow input limits require an upload admission snapshot")
        return self.upload_admission

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
        admission = self._require_upload_admission()
        admission_ceilings = {
            "file_max_size_bytes": admission.session_file_maximum_bytes,
            "audio_max_size_bytes": admission.session_audio_maximum_bytes,
        }
        for field_name, ceiling in admission_ceilings.items():
            requested = patch.get(field_name)
            if requested is not None and requested > ceiling:
                raise BadRequestException(
                    f"{field_name} cannot exceed the current upload admission ceiling of {ceiling} bytes.",
                    code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
                    context={
                        "field": field_name,
                        "requested_bytes": requested,
                        "maximum_bytes": ceiling,
                    },
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

    async def get_mapped_execution_policy_resolved(self) -> FlowMappedExecutionPolicy:
        tenant = await self._get_tenant_for_flow_settings()
        return resolve_flow_mapped_execution_policy(
            getattr(tenant, "flow_settings", None)
        )

    @validate_permissions(Permission.ADMIN)
    async def get_mapped_execution_policy(self) -> FlowMappedExecutionPolicyPublic:
        policy = await self.get_mapped_execution_policy_resolved()
        return FlowMappedExecutionPolicyPublic(
            version=policy.version,
            max_provider_calls_per_mapped_step=(
                policy.max_provider_calls_per_mapped_step
            ),
            max_estimated_input_tokens_per_mapped_step=(
                policy.max_estimated_input_tokens_per_mapped_step
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def update_mapped_execution_policy(
        self,
        payload: FlowMappedExecutionPolicyUpdate,
    ) -> FlowMappedExecutionPolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one mapped execution policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        previous = await self.get_mapped_execution_policy()
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_mapped_execution_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            remove_keys={key for key, value in patch.items() if value is None},
            **{key: value for key, value in patch.items() if value is not None},
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_mapped_execution_policy()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated mapped execution policy",
            metadata={
                "setting": "mapped_execution_policy",
                "changes": {
                    key: {"old": getattr(previous, key), "new": getattr(updated, key)}
                    for key in patch
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_rag_evidence_policy(self) -> FlowRagEvidencePolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        policy = resolve_flow_rag_evidence_policy(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
        )
        return FlowRagEvidencePolicyPublic(
            version=policy.version,
            max_sources_with_recorded_passages=(
                policy.max_sources_with_recorded_passages
            ),
            max_recorded_passages_per_source=policy.max_recorded_passages_per_source,
            max_recorded_passage_bytes=policy.max_recorded_passage_bytes,
            max_recorded_passage_bytes_per_step=(
                policy.max_recorded_passage_bytes_per_step
            ),
            max_recorded_passage_bytes_per_run_view=(
                policy.max_recorded_passage_bytes_per_run_view
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def update_rag_evidence_policy(
        self,
        payload: FlowRagEvidencePolicyUpdate,
    ) -> FlowRagEvidencePolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one knowledge evidence policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        previous = await self.get_rag_evidence_policy()
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_flow_rag_evidence_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            remove_keys={key for key, value in patch.items() if value is None},
            **{key: value for key, value in patch.items() if value is not None},
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_rag_evidence_policy()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated knowledge evidence policy",
            metadata={
                "setting": "flow_rag_evidence_policy",
                "changes": {
                    key: {"old": getattr(previous, key), "new": getattr(updated, key)}
                    for key in patch
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_ai_builder_budget_settings(self) -> AIBuilderBudgetSettingsPublic:
        policy = await self.get_ai_builder_budget_policy()
        return AIBuilderBudgetSettingsPublic(
            conversation_safety_buffer_tokens=policy.conversation_safety_buffer_tokens,
            minimum_conversation_budget_tokens=policy.minimum_conversation_budget_tokens,
            max_attachments=policy.max_attachments,
            max_message_chars=policy.max_message_chars,
            max_template_inspection_uncompressed_bytes=(
                policy.max_template_inspection_uncompressed_bytes
            ),
            max_template_placeholders=policy.max_template_placeholders,
            max_attachments_hard_limit=AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
            max_message_chars_hard_limit=AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
            max_template_inspection_uncompressed_bytes_hard_limit=(
                AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
            ),
            max_template_placeholders_hard_limit=(
                AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT
            ),
            max_template_archive_entries_per_file_hard_limit=(
                MAX_TEMPLATE_ARCHIVE_ENTRIES
            ),
            max_template_uncompressed_bytes_per_file_hard_limit=(
                MAX_TEMPLATE_UNCOMPRESSED_BYTES
            ),
            max_planning_state_payload_bytes_hard_limit=(
                PLANNING_STATE_PAYLOAD_CAP_BYTES
            ),
            budget_token_hard_limit=AI_BUILDER_BUDGET_MAX_TOKENS,
        )

    async def get_ai_builder_budget_policy(self) -> AIBuilderBudgetPolicy:
        """Resolve effective Builder settings for authenticated tenant services."""

        tenant = await self._get_tenant_for_flow_settings()
        return resolve_ai_builder_budget_policy(getattr(tenant, "flow_settings", None))

    @validate_permissions(Permission.ADMIN)
    async def update_ai_builder_budget_settings(
        self,
        payload: AIBuilderBudgetSettingsUpdate,
    ) -> AIBuilderBudgetSettingsPublic:
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise BadRequestException(
                "At least one AI Builder setting must be provided."
            )
        previous = await self.get_ai_builder_budget_settings()
        tenant = await self._get_tenant_for_flow_settings()
        next_flow_settings = apply_ai_builder_budget_policy_patch(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None)),
            **patch,
            remove_keys={key for key, value in patch.items() if value is None},
        )
        await self._persist_flow_settings(next_flow_settings)
        updated = await self.get_ai_builder_budget_settings()
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated AI Builder settings",
            metadata={
                "setting": "ai_builder_budget_settings",
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
        state = (
            await self.data_retention_service.get_flow_retention_control_plane_state(
                tenant_id=self.user.tenant_id
            )
        )
        return FlowRetentionPolicyPublic(
            run_debug_evidence_days=policy.run_debug_evidence_days,
            flow_run_history_retention_days=(state.organization_run_history_days),
            flow_runtime_upload_abandonment_days=(
                state.runtime_upload_abandonment_days
            ),
            flow_run_history_minimum_retention_days=(
                state.organization_minimum_retention_days
            ),
            flow_run_history_no_purge=state.organization_no_purge,
            effective_state=FlowRetentionEffectiveStatePublic.from_domain(state),
        )

    @validate_permissions(Permission.ADMIN)
    async def preview_flow_retention_policy(
        self,
        payload: FlowRetentionOrganizationPreviewRequest,
    ) -> FlowRetentionImpactPreviewPublic:
        preview = await self.data_retention_service.preview_flow_retention_organization_change(
            tenant_id=self.user.tenant_id,
            proposal=FlowRetentionOrganizationProposal(
                flow_run_history_retention_days=(
                    payload.flow_run_history_retention_days
                ),
                flow_runtime_upload_abandonment_days=(
                    payload.flow_runtime_upload_abandonment_days
                ),
                flow_run_history_minimum_retention_days=(
                    payload.flow_run_history_minimum_retention_days
                ),
                flow_run_history_no_purge=payload.flow_run_history_no_purge,
            ),
        )
        return FlowRetentionImpactPreviewPublic.from_domain(preview)

    @validate_permissions(Permission.ADMIN)
    async def update_flow_retention_policy(
        self,
        payload: FlowRetentionPolicyUpdate,
    ) -> FlowRetentionPolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        patch.pop("confirmation", None)
        if not patch:
            raise BadRequestException(
                "At least one flow retention policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        confirmation = (
            FlowRetentionChangeConfirmation(
                expected_control_plane_version=(
                    payload.confirmation.expected_control_plane_version
                ),
                expected_preview_hash=payload.confirmation.expected_preview_hash,
                previewed_at=payload.confirmation.previewed_at,
            )
            if payload.confirmation is not None
            else None
        )
        decision = await self.data_retention_service.prepare_flow_retention_organization_change(
            tenant_id=self.user.tenant_id,
            run_history_patch=FlowRetentionValuePatch(
                is_set="flow_run_history_retention_days" in payload.model_fields_set,
                value=payload.flow_run_history_retention_days,
            ),
            upload_abandonment_patch=FlowRetentionValuePatch(
                is_set="flow_runtime_upload_abandonment_days"
                in payload.model_fields_set,
                value=payload.flow_runtime_upload_abandonment_days,
            ),
            minimum_retention_patch=FlowRetentionValuePatch(
                is_set="flow_run_history_minimum_retention_days"
                in payload.model_fields_set,
                value=payload.flow_run_history_minimum_retention_days,
            ),
            no_purge_patch=FlowRetentionBoolPatch(
                is_set="flow_run_history_no_purge" in payload.model_fields_set,
                value=payload.flow_run_history_no_purge,
            ),
            confirmation=confirmation,
        )
        tenant = await self._get_tenant_for_flow_settings()
        current_debug_policy = resolve_flow_retention_policy(
            getattr(tenant, "flow_settings", None)
        )
        next_flow_settings = normalize_flow_settings_object(
            getattr(tenant, "flow_settings", None)
        )
        if "run_debug_evidence_days" in payload.model_fields_set:
            try:
                next_flow_settings = apply_flow_retention_policy_patch(
                    next_flow_settings,
                    run_debug_evidence_days=payload.run_debug_evidence_days,
                    remove_keys=(
                        {"run_debug_evidence_days"}
                        if payload.run_debug_evidence_days is None
                        else set()
                    ),
                )
            except ValueError as error:
                raise BadRequestException(
                    str(error),
                    code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
                ) from error
        await self.tenant_repo.update_tenant(
            TenantUpdate(
                id=self.user.tenant_id,
                flow_settings=next_flow_settings,
                flow_run_history_retention_days=(
                    decision.new_policy.flow_run_history_retention_days
                ),
                flow_runtime_upload_abandonment_days=(
                    decision.new_policy.flow_runtime_upload_abandonment_days
                ),
                flow_run_history_minimum_retention_days=(
                    decision.new_policy.flow_run_history_minimum_retention_days
                ),
                flow_run_history_no_purge=(
                    decision.new_policy.flow_run_history_no_purge
                ),
            )
        )
        activation_time = datetime.now(timezone.utc)
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow retention policy",
            metadata={
                "old_policy": {
                    "run_debug_evidence_days": (
                        current_debug_policy.run_debug_evidence_days
                    ),
                    "flow_run_history_retention_days": (
                        decision.old_policy.flow_run_history_retention_days
                    ),
                    "flow_runtime_upload_abandonment_days": (
                        decision.old_policy.flow_runtime_upload_abandonment_days
                    ),
                    "flow_run_history_minimum_retention_days": (
                        decision.old_policy.flow_run_history_minimum_retention_days
                    ),
                    "flow_run_history_no_purge": (
                        decision.old_policy.flow_run_history_no_purge
                    ),
                },
                "new_policy": {
                    "run_debug_evidence_days": payload.run_debug_evidence_days
                    if "run_debug_evidence_days" in payload.model_fields_set
                    else current_debug_policy.run_debug_evidence_days,
                    "flow_run_history_retention_days": (
                        decision.new_policy.flow_run_history_retention_days
                    ),
                    "flow_runtime_upload_abandonment_days": (
                        decision.new_policy.flow_runtime_upload_abandonment_days
                    ),
                    "flow_run_history_minimum_retention_days": (
                        decision.new_policy.flow_run_history_minimum_retention_days
                    ),
                    "flow_run_history_no_purge": (
                        decision.new_policy.flow_run_history_no_purge
                    ),
                },
                "preview": (
                    decision.preview.audit_summary()
                    if decision.preview is not None
                    else None
                ),
                "activation": {
                    "destructive_change": decision.destructive_change,
                    "activated_at": activation_time.isoformat(),
                },
            },
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
