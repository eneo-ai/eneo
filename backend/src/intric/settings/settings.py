from dataclasses import asdict
from uuid import UUID

from pydantic import BaseModel, Field

from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from intric.flows.flow_document_limits import FLOW_DOCUMENT_RENDER_HARD_LIMITS
from intric.flows.flow_input_limits import (
    FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
    FLOW_INPUT_MAX_FILES_COUNT,
    FLOW_INPUT_MAX_LIMIT_BYTES,
    FLOW_INPUT_MIN_LIMIT_BYTES,
)
from intric.flows.runtime.document_rendering.limits import DocumentRenderLimits
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
    file_max_size_bytes: int = Field(
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        le=FLOW_INPUT_MAX_LIMIT_BYTES,
    )
    audio_max_size_bytes: int = Field(
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        le=FLOW_INPUT_MAX_LIMIT_BYTES,
    )
    max_files_per_run: int | None = Field(
        ...,
        ge=1,
        le=FLOW_INPUT_MAX_FILES_COUNT,
        description="Null means no tenant-level file count ceiling.",
    )
    audio_max_files_per_run: int | None = Field(
        ...,
        ge=1,
        le=FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
        description="Null means no tenant-level audio file count ceiling.",
    )


class FlowInputLimitsUpdate(BaseModel):
    file_max_size_bytes: int | None = Field(
        default=None,
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        le=FLOW_INPUT_MAX_LIMIT_BYTES,
        description="Set the tenant override, or send null to use the deployment default.",
    )
    audio_max_size_bytes: int | None = Field(
        default=None,
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        le=FLOW_INPUT_MAX_LIMIT_BYTES,
        description="Set the tenant override, or send null to use the deployment default.",
    )
    max_files_per_run: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_INPUT_MAX_FILES_COUNT,
        description="Set the tenant ceiling, or send null for no tenant-level ceiling.",
    )
    audio_max_files_per_run: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
        description="Set the tenant ceiling, or send null to use the default audio ceiling.",
    )


class FlowDocumentRenderLimitsPublic(BaseModel):
    max_source_chars: int = Field(
        ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_source_chars
    )
    max_blocks: int = Field(ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_blocks)
    max_text_chars: int = Field(
        ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_text_chars
    )
    max_table_rows: int = Field(
        ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_rows
    )
    max_table_columns: int = Field(
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_columns,
    )
    max_table_cells: int = Field(
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_cells,
    )
    max_cell_chars: int = Field(
        ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_cell_chars
    )
    max_list_items: int = Field(
        ge=1, le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_list_items
    )
    max_structured_nodes: int = Field(
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_structured_nodes,
    )
    max_structured_depth: int = Field(
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_structured_depth,
    )
    max_object_fields: int = Field(
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_object_fields,
    )

    @classmethod
    def from_domain(
        cls,
        limits: DocumentRenderLimits,
    ) -> "FlowDocumentRenderLimitsPublic":
        return cls(**asdict(limits))


class FlowDocumentRenderLimitsUpdate(BaseModel):
    max_source_chars: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_source_chars,
    )
    max_blocks: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_blocks,
    )
    max_text_chars: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_text_chars,
    )
    max_table_rows: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_rows,
    )
    max_table_columns: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_columns,
    )
    max_table_cells: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_table_cells,
    )
    max_cell_chars: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_cell_chars,
    )
    max_list_items: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_list_items,
    )
    max_structured_nodes: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_structured_nodes,
    )
    max_structured_depth: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_structured_depth,
    )
    max_object_fields: int | None = Field(
        default=None,
        ge=1,
        le=FLOW_DOCUMENT_RENDER_HARD_LIMITS.max_object_fields,
    )


class AIBuilderBudgetSettingsPublic(BaseModel):
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    unknown_model_context_window_tokens: int | None = None


class AIBuilderBudgetSettingsUpdate(BaseModel):
    conversation_safety_buffer_tokens: int | None = None
    minimum_conversation_budget_tokens: int | None = None
    unknown_model_context_window_tokens: int | None = None


class FlowEvidencePolicyPublic(BaseModel):
    allow_sensitive_flow_exports: bool = False
    allow_space_admin_raw_export_class3: bool = False
    allow_run_owner_raw_export_class3: bool = False
    allow_service_key_raw_export_class3: bool = False


class FlowEvidencePolicyUpdate(BaseModel):
    allow_sensitive_flow_exports: bool | None = None
    allow_space_admin_raw_export_class3: bool | None = None
    allow_run_owner_raw_export_class3: bool | None = None
    allow_service_key_raw_export_class3: bool | None = None


class FlowRetentionPolicyPublic(BaseModel):
    shared_default_days: int | None = None
    source_audio_days: int | None = None
    transcript_text_days: int | None = None
    generated_artifact_days: int | None = None
    run_debug_evidence_days: int | None = None


class FlowRetentionPolicyUpdate(BaseModel):
    shared_default_days: int | None = None
    source_audio_days: int | None = None
    transcript_text_days: int | None = None
    generated_artifact_days: int | None = None
    run_debug_evidence_days: int | None = None
