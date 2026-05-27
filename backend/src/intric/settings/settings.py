from dataclasses import asdict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

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


FLOW_INPUT_LIMITS_PUBLIC_EXAMPLE: JsonDict = {
    "file_max_size_bytes": 52428800,
    "audio_max_size_bytes": 104857600,
    "max_files_per_run": 20,
    "audio_max_files_per_run": 5,
}

FLOW_INPUT_LIMITS_UPDATE_EXAMPLE: JsonDict = {
    "file_max_size_bytes": 52428800,
    "audio_max_size_bytes": None,
    "max_files_per_run": 20,
    "audio_max_files_per_run": None,
}

FLOW_DOCUMENT_RENDER_LIMITS_EXAMPLE: JsonDict = {
    "max_source_chars": 500000,
    "max_blocks": 2000,
    "max_text_chars": 500000,
    "max_table_rows": 5000,
    "max_table_columns": 50,
    "max_table_cells": 50000,
    "max_cell_chars": 20000,
    "max_list_items": 5000,
    "max_structured_nodes": 10000,
    "max_structured_depth": 32,
    "max_object_fields": 200,
}

FLOW_DOCUMENT_RENDER_LIMITS_UPDATE_EXAMPLE: JsonDict = {
    "max_source_chars": 500000,
    "max_blocks": None,
    "max_table_rows": 5000,
}

FLOW_RUNTIME_POLICY_EXAMPLE: JsonDict = {
    "default_step_timeout_seconds": 900,
    "max_step_timeout_seconds": 1800,
    "hard_ceiling_seconds": 3600,
}

FLOW_RUNTIME_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "default_step_timeout_seconds": 900,
    "max_step_timeout_seconds": None,
}

FLOW_EVIDENCE_POLICY_EXAMPLE: JsonDict = {
    "allow_sensitive_flow_exports": False,
    "allow_space_admin_raw_export_class3": False,
    "allow_run_owner_raw_export_class3": False,
    "allow_service_key_raw_export_class3": False,
}

FLOW_EVIDENCE_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "allow_sensitive_flow_exports": False,
    "allow_space_admin_raw_export_class3": True,
}

FLOW_RETENTION_POLICY_EXAMPLE: JsonDict = {
    "run_debug_evidence_days": 7,
}

FLOW_RETENTION_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "run_debug_evidence_days": 14,
}


class FlowInputLimitsPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_INPUT_LIMITS_PUBLIC_EXAMPLE}
    )

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
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_INPUT_LIMITS_UPDATE_EXAMPLE}
    )

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
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_DOCUMENT_RENDER_LIMITS_EXAMPLE}
    )

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
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_DOCUMENT_RENDER_LIMITS_UPDATE_EXAMPLE}
    )

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


class FlowRuntimePolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUNTIME_POLICY_EXAMPLE}
    )

    default_step_timeout_seconds: int = Field(ge=1)
    max_step_timeout_seconds: int = Field(ge=1)
    hard_ceiling_seconds: int = Field(
        ge=1,
        description="Deployment hard ceiling after reserving worker task shutdown buffer.",
    )


class FlowRuntimePolicyUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUNTIME_POLICY_UPDATE_EXAMPLE}
    )

    default_step_timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Set the tenant default per-step LLM timeout, or send null to use the deployment default.",
    )
    max_step_timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Set the tenant maximum per-step LLM timeout, or send null to use the deployment ceiling.",
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
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_EVIDENCE_POLICY_EXAMPLE}
    )

    allow_sensitive_flow_exports: bool = False
    allow_space_admin_raw_export_class3: bool = False
    allow_run_owner_raw_export_class3: bool = False
    allow_service_key_raw_export_class3: bool = False


class FlowEvidencePolicyUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_EVIDENCE_POLICY_UPDATE_EXAMPLE}
    )

    allow_sensitive_flow_exports: bool | None = None
    allow_space_admin_raw_export_class3: bool | None = None
    allow_run_owner_raw_export_class3: bool | None = None
    allow_service_key_raw_export_class3: bool | None = None


class FlowRetentionPolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RETENTION_POLICY_EXAMPLE}
    )

    run_debug_evidence_days: int | None = None


class FlowRetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RETENTION_POLICY_UPDATE_EXAMPLE},
    )

    run_debug_evidence_days: int | None = None
