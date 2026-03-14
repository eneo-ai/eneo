from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from intric.main.models import InDB


class SettingsBase(BaseModel):
    chatbot_widget: dict = {}


class SettingsUpsert(SettingsBase):
    user_id: UUID


class SettingsInDB(SettingsUpsert, InDB):
    pass


class SettingsPublic(SettingsBase):
    using_templates: bool = False  # Feature flag for template management
    tenant_credentials_enabled: bool = False  # Global config for tenant credential enforcement
    audit_logging_enabled: bool = True  # Feature flag for audit logging (default enabled for backward compat)
    provisioning: bool = False  # JIT provisioning - auto-create users on SSO login
    api_key_scope_enforcement: bool = True  # Per-tenant scope enforcement toggle
    api_key_strict_mode: bool = False  # Per-tenant strict mode toggle (default off for staged rollout)
    api_key_expiry_notifications: bool = True  # Per-tenant API key expiry notifications toggle


class GetModelsResponse(BaseModel):
    completion_models: list[CompletionModelPublic]
    embedding_models: list[EmbeddingModelPublicLegacy]


class ToggleSettingUpdate(BaseModel):
    enabled: bool
