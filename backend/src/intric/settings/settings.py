from uuid import UUID

from pydantic import BaseModel, Field

from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from intric.main.models import InDB


class SettingsBase(BaseModel):
    chatbot_widget: dict[str, object] = Field(default_factory=dict)


class SettingsUpsert(SettingsBase):
    user_id: UUID


class SettingsInDB(SettingsUpsert, InDB):
    pass


class SettingsPublic(SettingsBase):
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


class FlowInputLimitsPublic(BaseModel):
    file_max_size_bytes: int
    audio_max_size_bytes: int
    max_files_per_run: int | None = None
    audio_max_files_per_run: int | None = None


class FlowInputLimitsUpdate(BaseModel):
    file_max_size_bytes: int | None = None
    audio_max_size_bytes: int | None = None
    max_files_per_run: int | None = None
    audio_max_files_per_run: int | None = None


class AIBuilderBudgetSettingsPublic(BaseModel):
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    unknown_model_context_window_tokens: int | None = None


class AIBuilderBudgetSettingsUpdate(BaseModel):
    conversation_safety_buffer_tokens: int | None = None
    minimum_conversation_budget_tokens: int | None = None
    unknown_model_context_window_tokens: int | None = None
