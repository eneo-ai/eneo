from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from eneo.main.models import InDB
from eneo.skills.domain.skill import (
    MAX_SKILL_ACTIVATIONS_PER_TURN,
    MAX_SKILL_ATTACHMENT_LIMIT,
    MAX_SKILL_CONTEXT_SHARE_PERCENT,
    MAX_SKILL_EXECUTION_BLOCK_REASON_LENGTH,
    MIN_SKILL_ACTIVATIONS_PER_TURN,
    MIN_SKILL_ATTACHMENT_LIMIT,
    MIN_SKILL_CONTEXT_SHARE_PERCENT,
    SkillExecutionBlock,
    SkillRuntimePolicy,
)


class SettingsBase(BaseModel):
    chatbot_widget: dict[str, object] = Field(default_factory=dict)


class SettingsUpsert(SettingsBase):
    user_id: UUID


class SettingsInDB(SettingsUpsert, InDB):
    pass


class SettingsPublic(SettingsBase):
    object_content_enabled: bool = False
    using_templates: bool = False  # Feature flag for template management
    tenant_credentials_enabled: bool = (
        False  # Global config for tenant credential enforcement
    )
    audit_logging_enabled: bool = (
        True  # Feature flag for audit logging (default enabled for backward compat)
    )
    provisioning: bool = False  # JIT provisioning - auto-create users on SSO login
    api_key_expiry_notifications: bool = (
        True  # Per-tenant API key expiry notifications toggle
    )


class GetModelsResponse(BaseModel):
    completion_models: list[CompletionModelPublic]
    embedding_models: list[EmbeddingModelPublicLegacy]


class ToggleSettingUpdate(BaseModel):
    enabled: bool


class SkillExecutionBlockUpdate(BaseModel):
    reason: str = Field(
        min_length=1,
        max_length=MAX_SKILL_EXECUTION_BLOCK_REASON_LENGTH,
    )


class SkillExecutionUnblockUpdate(SkillExecutionBlockUpdate):
    expected_block_id: UUID


class SkillExecutionBlockPublic(BaseModel):
    id: UUID
    skill_id: UUID
    blocked_by_user_id: UUID
    reason: str
    blocked_at: datetime

    @classmethod
    def from_domain(
        cls,
        block: SkillExecutionBlock,
    ) -> "SkillExecutionBlockPublic":
        return cls(
            id=block.id,
            skill_id=block.skill_id,
            blocked_by_user_id=block.blocked_by_user_id,
            reason=block.reason,
            blocked_at=block.blocked_at,
        )


class SkillExecutionBlockState(BaseModel):
    skill_id: UUID
    block: SkillExecutionBlockPublic | None

    @classmethod
    def from_domain(
        cls,
        *,
        skill_id: UUID,
        block: SkillExecutionBlock | None,
    ) -> "SkillExecutionBlockState":
        return cls(
            skill_id=skill_id,
            block=(
                SkillExecutionBlockPublic.from_domain(block)
                if block is not None
                else None
            ),
        )


class SkillRuntimePolicyFieldBounds(BaseModel):
    minimum: int
    maximum: int


class SkillRuntimePolicyEditableBounds(BaseModel):
    max_attached_skills: SkillRuntimePolicyFieldBounds
    context_share_percent: SkillRuntimePolicyFieldBounds
    max_activations_per_turn: SkillRuntimePolicyFieldBounds


class SkillRuntimePolicyPublic(BaseModel):
    selective_activation_enabled: bool
    max_attached_skills: int
    context_share_percent: int
    max_activations_per_turn: int
    editable_bounds: SkillRuntimePolicyEditableBounds

    @classmethod
    def from_domain(cls, policy: SkillRuntimePolicy) -> "SkillRuntimePolicyPublic":
        return cls(
            selective_activation_enabled=policy.selective_activation_enabled,
            max_attached_skills=policy.max_attached_skills,
            context_share_percent=policy.context_share_percent,
            max_activations_per_turn=policy.max_activations_per_turn,
            editable_bounds=SkillRuntimePolicyEditableBounds(
                max_attached_skills=SkillRuntimePolicyFieldBounds(
                    minimum=MIN_SKILL_ATTACHMENT_LIMIT,
                    maximum=MAX_SKILL_ATTACHMENT_LIMIT,
                ),
                context_share_percent=SkillRuntimePolicyFieldBounds(
                    minimum=MIN_SKILL_CONTEXT_SHARE_PERCENT,
                    maximum=MAX_SKILL_CONTEXT_SHARE_PERCENT,
                ),
                max_activations_per_turn=SkillRuntimePolicyFieldBounds(
                    minimum=MIN_SKILL_ACTIVATIONS_PER_TURN,
                    maximum=MAX_SKILL_ACTIVATIONS_PER_TURN,
                ),
            ),
        )


class SkillRuntimePolicyUpdate(BaseModel):
    """Full replacement of the one four-field tenant policy."""

    selective_activation_enabled: bool
    max_attached_skills: int = Field(
        ge=MIN_SKILL_ATTACHMENT_LIMIT,
        le=MAX_SKILL_ATTACHMENT_LIMIT,
    )
    context_share_percent: int = Field(
        ge=MIN_SKILL_CONTEXT_SHARE_PERCENT,
        le=MAX_SKILL_CONTEXT_SHARE_PERCENT,
    )
    max_activations_per_turn: int = Field(
        ge=MIN_SKILL_ACTIVATIONS_PER_TURN,
        le=MAX_SKILL_ACTIVATIONS_PER_TURN,
    )

    def to_domain(self) -> SkillRuntimePolicy:
        return SkillRuntimePolicy(
            selective_activation_enabled=self.selective_activation_enabled,
            max_attached_skills=self.max_attached_skills,
            context_share_percent=self.context_share_percent,
            max_activations_per_turn=self.max_activations_per_turn,
        )


class SkillRuntimeModelProjection(BaseModel):
    """Read-only policy allowance for one accessible completion model. The
    exact LiteLLM-measured configuration fit belongs to save-time validation,
    not this projection."""

    completion_model_id: UUID
    name: str
    nickname: str | None
    max_input_tokens: int
    supports_tool_calling: bool
    skill_context_token_allowance: int


class SkillRuntimeModelProjections(BaseModel):
    context_share_percent: int
    models: list[SkillRuntimeModelProjection]
