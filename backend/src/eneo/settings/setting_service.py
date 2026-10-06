from collections.abc import Callable, Mapping, Sequence
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
)
from eneo.data_retention.infrastructure.retention_lock import (
    RetentionSubject,
    acquire_exclusive,
)
from eneo.files.docx_template_validation import (
    MAX_TEMPLATE_ARCHIVE_ENTRIES,
    MAX_TEMPLATE_UNCOMPRESSED_BYTES,
)
from eneo.files.file_reference import file_reference_base_url
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    apply_ai_builder_budget_policy_patch,
    resolve_ai_builder_budget_policy,
)
from eneo.flows.ai_builder.planning_state import PLANNING_STATE_PAYLOAD_CAP_BYTES
from eneo.flows.application.flow_retention_authz import require_retention_manage
from eneo.flows.domain.flow_run_retention_policy import (
    FLOW_RETENTION_REASON_REQUIRED_CODE,
)
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    apply_flow_mapped_execution_policy_patch,
    mapped_call_ceiling_source,
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
    AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS,
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
    audio_duration_ceiling_seconds,
    effective_upload_ceiling_bytes,
    flow_audio_decode_limits,
    resolve_flow_input_limits,
)
from eneo.flows.flow_retention_policy import (
    DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS,
    apply_flow_retention_policy_patch,
    resolve_flow_retention_policy,
)
from eneo.flows.flow_runtime_policy import (
    FlowRuntimePolicy,
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
from eneo.tenants.tenant_repo import FlowSettingsChange, TenantRepository
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.feature_flag.feature_flag import FeatureFlag
    from eneo.feature_flag.feature_flag_service import FeatureFlagService

logger = get_logger(__name__)

FLOW_SETTINGS_INVALID_PAYLOAD_CODE = "flow_settings_invalid_payload"


def _upload_window_days(days: int | None) -> int:
    """The window that applies: the tenant's days, or the default when unset."""
    return DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS if days is None else days


_UPLOAD_ABANDONMENT_DAYS_COLUMN = "flow_runtime_upload_abandonment_days"


def _flow_runtime_policy_public(policy: FlowRuntimePolicy) -> FlowRuntimePolicyPublic:
    return FlowRuntimePolicyPublic(
        default_step_timeout_seconds=policy.default_step_timeout_seconds,
        max_step_timeout_seconds=policy.max_step_timeout_seconds,
        hard_ceiling_seconds=policy.hard_ceiling_seconds,
        max_concurrent_runs=policy.max_concurrent_runs,
        max_concurrent_runs_override=policy.max_concurrent_runs_override,
        max_concurrent_runs_capacity=policy.max_concurrent_runs_capacity,
    )


def _mapped_execution_policy_public(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowMappedExecutionPolicyPublic:
    policy = resolve_flow_mapped_execution_policy(tenant_flow_settings)
    return FlowMappedExecutionPolicyPublic(
        version=policy.version,
        max_provider_calls_per_mapped_step=policy.max_provider_calls_per_mapped_step,
        max_estimated_input_tokens_per_mapped_step=(
            policy.max_estimated_input_tokens_per_mapped_step
        ),
        max_provider_calls_source=mapped_call_ceiling_source(tenant_flow_settings),
        deployment_default_max_provider_calls=(
            get_app_settings().flow_mapped_step_max_provider_calls_default
        ),
    )


def _rag_evidence_policy_public(
    flow_settings: dict[str, Any] | None,
) -> FlowRagEvidencePolicyPublic:
    policy = resolve_flow_rag_evidence_policy(flow_settings)
    return FlowRagEvidencePolicyPublic(
        version=policy.version,
        max_sources_with_recorded_passages=policy.max_sources_with_recorded_passages,
        max_recorded_passages_per_source=policy.max_recorded_passages_per_source,
        max_recorded_passage_bytes=policy.max_recorded_passage_bytes,
        max_recorded_passage_bytes_per_step=(
            policy.max_recorded_passage_bytes_per_step
        ),
        max_recorded_passage_bytes_per_run_view=(
            policy.max_recorded_passage_bytes_per_run_view
        ),
    )


def _ai_builder_budget_public(
    policy: AIBuilderBudgetPolicy,
) -> AIBuilderBudgetSettingsPublic:
    return AIBuilderBudgetSettingsPublic(
        conversation_safety_buffer_tokens=policy.conversation_safety_buffer_tokens,
        minimum_conversation_budget_tokens=policy.minimum_conversation_budget_tokens,
        review_evidence_max_input_tokens=policy.review_evidence_max_input_tokens,
        review_investigation_evidence_max_tokens=(
            policy.review_investigation_evidence_max_tokens
        ),
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
        review_investigation_evidence_ceiling_tokens=(
            AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS
        ),
        max_template_archive_entries_per_file_hard_limit=MAX_TEMPLATE_ARCHIVE_ENTRIES,
        max_template_uncompressed_bytes_per_file_hard_limit=(
            MAX_TEMPLATE_UNCOMPRESSED_BYTES
        ),
        max_planning_state_payload_bytes_hard_limit=PLANNING_STATE_PAYLOAD_CAP_BYTES,
        budget_token_hard_limit=AI_BUILDER_BUDGET_MAX_TOKENS,
    )


def _flow_evidence_policy_public(
    flow_settings: dict[str, Any] | None,
) -> FlowEvidencePolicyPublic:
    policy = resolve_flow_evidence_policy(flow_settings)
    return FlowEvidencePolicyPublic(
        allow_sensitive_flow_exports=policy.allow_sensitive_flow_exports,
        allow_space_admin_raw_export_class3=policy.allow_space_admin_raw_export_class3,
        allow_run_owner_raw_export_class3=policy.allow_run_owner_raw_export_class3,
        allow_service_key_raw_export_class3=policy.allow_service_key_raw_export_class3,
    )


def _flow_retention_policy_public(
    flow_settings: dict[str, Any] | None, upload_abandonment_days: int | None
) -> FlowRetentionPolicyPublic:
    return FlowRetentionPolicyPublic(
        run_debug_evidence_days=resolve_flow_retention_policy(
            flow_settings
        ).run_debug_evidence_days,
        flow_runtime_upload_abandonment_days=upload_abandonment_days,
    )


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
                    skill_context_token_allowance=(
                        skill_context_token_allowance(
                            max_input_tokens=model.max_input_tokens,
                            context_share_percent=policy.context_share_percent,
                        )
                        if model.max_input_tokens is not None
                        else None
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

        whats_new_enabled = (
            overrides["whats_new_enabled"]
            if "whats_new_enabled" in overrides
            else await self.feature_flag_service.check_is_feature_enabled(
                feature_name="whats_new_enabled",
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
            whats_new_enabled=whats_new_enabled,
            file_references_enabled=bool(file_reference_base_url(app_settings)),
            object_store_configured=self.object_content.object_store_configured,
            flow_transcription_service_configured=(
                app_settings.flow_transcription_service_configured
            ),
            flow_transcription_service_mode=(
                app_settings.flow_transcription_service_mode
                if app_settings.flow_transcription_service_configured
                else None
            ),
            sharepoint_fixture_mode_available=(
                app_settings.sharepoint_fixture_mode_active
            ),
            developer_tools_available=app_settings.is_development,
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

    async def _update_flow_settings(
        self,
        transform: Callable[[dict[str, Any] | None], dict[str, Any]],
        *,
        extra_values: Mapping[str, Any] | None = None,
        read_columns: Sequence[str] = (),
    ) -> FlowSettingsChange:
        """Change only this setting's keys of tenants.flow_settings.

        The tenant repository locks the row and reads it fresh, so a concurrent
        change to another setting's keys is kept. The returned change carries
        the locked before-values that the audit reports as old.
        """

        def normalized(current: dict[str, Any] | None) -> dict[str, Any]:
            return normalize_flow_settings_object(transform(current))

        return await self.tenant_repo.update_flow_settings(
            self.user.tenant_id,
            normalized,
            extra_values=extra_values,
            read_columns=read_columns,
        )

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
        tenant = await self._get_tenant_for_flow_settings()
        return self._flow_input_limits_public(getattr(tenant, "flow_settings", None))

    def _flow_input_limits_public(
        self, flow_settings: dict[str, Any] | None
    ) -> FlowInputLimitsPublic:
        admission = self._require_upload_admission()
        limits = resolve_flow_input_limits(flow_settings, defaults=admission)
        return FlowInputLimitsPublic(
            file_max_size_bytes=limits.file_max_size_bytes,
            audio_max_size_bytes=limits.audio_max_size_bytes,
            max_files_per_run=limits.max_files_per_run,
            audio_max_files_per_run=limits.audio_max_files_per_run,
            audio_max_duration_seconds=flow_audio_decode_limits(
                limits
            ).longest_audio_seconds,
            audio_max_duration_ceiling_seconds=audio_duration_ceiling_seconds(),
            # The admission ceiling is the writable bound; exposing it lets the
            # admin UI validate inline instead of surfacing a save-time error.
            file_max_size_ceiling_bytes=effective_upload_ceiling_bytes(
                admission.session_file_maximum_bytes
            ),
            audio_max_size_ceiling_bytes=effective_upload_ceiling_bytes(
                admission.session_audio_maximum_bytes
            ),
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
            "file_max_size_bytes": effective_upload_ceiling_bytes(
                admission.session_file_maximum_bytes
            ),
            "audio_max_size_bytes": effective_upload_ceiling_bytes(
                admission.session_audio_maximum_bytes
            ),
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
        requested_seconds = patch.get("audio_max_duration_seconds")
        ceiling_seconds = audio_duration_ceiling_seconds()
        if requested_seconds is not None and requested_seconds > ceiling_seconds:
            raise BadRequestException(
                f"audio_max_duration_seconds cannot exceed the deployment ceiling of {ceiling_seconds} seconds.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
                context={
                    "field": "audio_max_duration_seconds",
                    "requested_seconds": requested_seconds,
                    "maximum_seconds": ceiling_seconds,
                },
            )
        remove_keys = {key for key, value in patch.items() if value is None}
        updated_values = {
            key: value for key, value in patch.items() if value is not None
        }
        change = await self._update_flow_settings(
            lambda current: apply_flow_input_limits_patch(
                current,
                remove_keys=remove_keys,
                **updated_values,
            )
        )
        previous = self._flow_input_limits_public(change.before)
        updated = self._flow_input_limits_public(change.after)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
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
        return FlowDocumentRenderLimitsPublic.from_domain(
            resolve_flow_document_render_limits(getattr(tenant, "flow_settings", None))
        )

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
        change = await self._update_flow_settings(
            lambda current: apply_flow_document_render_limits_patch(
                current,
                remove_keys={key for key, value in patch.items() if value is None},
                **{key: value for key, value in patch.items() if value is not None},
            )
        )
        previous = FlowDocumentRenderLimitsPublic.from_domain(
            resolve_flow_document_render_limits(change.before)
        )
        updated = FlowDocumentRenderLimitsPublic.from_domain(
            resolve_flow_document_render_limits(change.after)
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
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

    async def get_flow_runtime_policy_resolved(self) -> FlowRuntimePolicy:
        tenant = await self._get_tenant_for_flow_settings()
        return resolve_flow_runtime_policy(getattr(tenant, "flow_settings", None))

    @validate_permissions(Permission.ADMIN)
    async def get_flow_runtime_policy(self) -> FlowRuntimePolicyPublic:
        return _flow_runtime_policy_public(
            await self.get_flow_runtime_policy_resolved()
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
        change = await self._update_flow_settings(
            lambda current: apply_flow_runtime_policy_patch(
                current,
                remove_keys={key for key, value in patch.items() if value is None},
                **{key: value for key, value in patch.items() if value is not None},
            )
        )
        previous = _flow_runtime_policy_public(
            resolve_flow_runtime_policy(change.before)
        )
        updated = _flow_runtime_policy_public(resolve_flow_runtime_policy(change.after))
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
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
        # The resolver owns the deployment-default fallback for every caller.
        return resolve_flow_mapped_execution_policy(
            getattr(tenant, "flow_settings", None)
        )

    @validate_permissions(Permission.ADMIN)
    async def get_mapped_execution_policy(self) -> FlowMappedExecutionPolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        return _mapped_execution_policy_public(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
        )

    @validate_permissions(Permission.ADMIN)
    async def update_mapped_execution_policy(
        self,
        payload: FlowMappedExecutionPolicyUpdate,
    ) -> FlowMappedExecutionPolicyPublic:
        patch = payload.model_dump(exclude_unset=True)
        restore_calls_default = bool(
            patch.pop("restore_max_provider_calls_default", False)
        )
        if not patch and not restore_calls_default:
            raise BadRequestException(
                "At least one mapped execution policy field must be provided.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        if restore_calls_default and "max_provider_calls_per_mapped_step" in patch:
            raise BadRequestException(
                "restore_max_provider_calls_default cannot be combined with "
                "max_provider_calls_per_mapped_step.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        remove_keys = {
            key
            for key, value in patch.items()
            if value is None and key != "max_provider_calls_per_mapped_step"
        }
        if restore_calls_default:
            remove_keys.add("max_provider_calls_per_mapped_step")
        change = await self._update_flow_settings(
            lambda current: apply_flow_mapped_execution_policy_patch(
                current,
                # A null call ceiling is an explicit opt-out that must keep blocking
                # mapped authoring beneath the deployment default; a null token
                # ceiling falls back to its absent-key state; the restore action
                # deletes the stored ceiling so the deployment default applies.
                disable_max_provider_calls=(
                    patch.get("max_provider_calls_per_mapped_step", ...) is None
                ),
                remove_keys=remove_keys,
                **{key: value for key, value in patch.items() if value is not None},
            )
        )
        previous = _mapped_execution_policy_public(change.before)
        updated = _mapped_execution_policy_public(change.after)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated mapped execution policy",
            metadata={
                "setting": "mapped_execution_policy",
                "restored_call_ceiling_default": restore_calls_default,
                "changes": {
                    key: {"old": getattr(previous, key), "new": getattr(updated, key)}
                    for key in (
                        *patch,
                        # A restore is a governance action; record the actual
                        # transition instead of only the flag.
                        *(
                            (
                                "max_provider_calls_per_mapped_step",
                                "max_provider_calls_source",
                            )
                            if restore_calls_default
                            else ()
                        ),
                    )
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def get_rag_evidence_policy(self) -> FlowRagEvidencePolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        return _rag_evidence_policy_public(
            cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
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
        change = await self._update_flow_settings(
            lambda current: apply_flow_rag_evidence_policy_patch(
                current,
                remove_keys={key for key, value in patch.items() if value is None},
                **{key: value for key, value in patch.items() if value is not None},
            )
        )
        previous = _rag_evidence_policy_public(change.before)
        updated = _rag_evidence_policy_public(change.after)
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
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
        return _ai_builder_budget_public(await self.get_ai_builder_budget_policy())

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
        change = await self._update_flow_settings(
            lambda current: apply_ai_builder_budget_policy_patch(
                current,
                **patch,
                remove_keys={key for key, value in patch.items() if value is None},
            )
        )
        previous = _ai_builder_budget_public(
            resolve_ai_builder_budget_policy(change.before)
        )
        updated = _ai_builder_budget_public(
            resolve_ai_builder_budget_policy(change.after)
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
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
        return _flow_evidence_policy_public(getattr(tenant, "flow_settings", None))

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
        change = await self._update_flow_settings(
            lambda current: apply_flow_evidence_policy_patch(
                current,
                **patch,
            )
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow evidence policy",
            metadata={"setting": "flow_evidence_policy", "changes": patch},
        )
        return _flow_evidence_policy_public(change.after)

    @validate_permissions(Permission.ADMIN)
    async def get_flow_retention_policy(self) -> FlowRetentionPolicyPublic:
        tenant = await self._get_tenant_for_flow_settings()
        return _flow_retention_policy_public(
            getattr(tenant, "flow_settings", None),
            getattr(tenant, _UPLOAD_ABANDONMENT_DAYS_COLUMN, None),
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
        upload_supplied = (
            "flow_runtime_upload_abandonment_days" in payload.model_fields_set
        )
        debug_supplied = "run_debug_evidence_days" in payload.model_fields_set
        if "reason" in payload.model_fields_set and not upload_supplied:
            raise BadRequestException(
                "A reason belongs to a change of the upload window.",
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            )
        if upload_supplied:
            # The upload window decides when gallring deletes: a retention
            # decision by a signed-in person with retention_manage, serialized
            # with open deletions before the tenant row is locked.
            require_retention_manage(self.user)
            await acquire_exclusive(
                self.tenant_repo.session, RetentionSubject.FLOW_HISTORY
            )

        def transform(current: dict[str, Any] | None) -> dict[str, Any]:
            if not debug_supplied:
                return normalize_flow_settings_object(current)
            return apply_flow_retention_policy_patch(
                normalize_flow_settings_object(current),
                run_debug_evidence_days=payload.run_debug_evidence_days,
                remove_keys=(
                    {"run_debug_evidence_days"}
                    if payload.run_debug_evidence_days is None
                    else set()
                ),
            )

        try:
            # Write only the fields this request supplies; the old values come
            # from the same locked read, so a concurrent save is neither undone
            # nor misreported.
            change = await self._update_flow_settings(
                transform,
                extra_values=(
                    {
                        "flow_runtime_upload_abandonment_days": (
                            payload.flow_runtime_upload_abandonment_days
                        )
                    }
                    if upload_supplied
                    else None
                ),
                read_columns=(_UPLOAD_ABANDONMENT_DAYS_COLUMN,),
            )
        except ValueError as error:
            raise BadRequestException(
                str(error),
                code=FLOW_SETTINGS_INVALID_PAYLOAD_CODE,
            ) from error
        old_upload_days = change.columns_before[_UPLOAD_ABANDONMENT_DAYS_COLUMN]
        new_upload_days = (
            payload.flow_runtime_upload_abandonment_days
            if upload_supplied
            else old_upload_days
        )
        previous = _flow_retention_policy_public(change.before, old_upload_days)
        updated = _flow_retention_policy_public(change.after, new_upload_days)
        if upload_supplied and old_upload_days != new_upload_days:
            await self._audit_upload_window_change(
                old_days=old_upload_days,
                new_days=new_upload_days,
                reason=payload.reason,
            )
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated flow retention policy",
            metadata={
                "old_policy": previous.model_dump(),
                "new_policy": updated.model_dump(),
            },
        )
        return updated

    async def _audit_upload_window_change(
        self, *, old_days: int | None, new_days: int | None, reason: str | None
    ) -> None:
        """The required record of a window change, from the locked before-value.

        A longer window postpones deletion, so it needs a reason; the exception
        rolls the change back with the request.
        """
        longer = _upload_window_days(new_days) > _upload_window_days(old_days)
        if longer and reason is None:
            raise BadRequestException(
                "Give a reason for keeping unused uploads and live transcripts longer.",
                code=FLOW_RETENTION_REASON_REQUIRED_CODE,
            )
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=(
                "Changed how long unused Flow uploads and live transcripts are kept."
            ),
            metadata={
                "scope": "organization",
                "scope_id": str(self.user.tenant_id),
                "setting": "runtime_upload_window_days",
                "previous_value": old_days,
                "new_value": new_days,
                "reason": reason,
            },
            required=True,
        )

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

    @validate_permissions(Permission.ADMIN)
    async def update_whats_new_setting(self, enabled: bool) -> SettingsPublic:
        """Toggle the What's new page, announcement and indicator for tenant."""
        old_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="whats_new_enabled",
            tenant_id=self.user.tenant_id,
        )
        await self._set_feature_flag_for_tenant(
            name="whats_new_enabled", enabled=enabled
        )

        settings = await self.repo.get(self.user.id)

        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description=f"Toggled whats_new_enabled to {enabled}",
            metadata={
                "setting": "whats_new_enabled",
                "changes": {"whats_new_enabled": {"old": old_enabled, "new": enabled}},
            },
        )

        return await self._build_settings_public(
            settings_in_db=settings,
            overrides={"whats_new_enabled": enabled},
        )
