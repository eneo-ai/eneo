from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.config import JsonDict
from pydantic.json_schema import SkipJsonSchema

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.flows.domain.rag_evidence_policy import (
    RAG_EVIDENCE_CEILINGS,
    RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY,
    RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY,
    RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY,
    RAG_EVIDENCE_MAX_SOURCES_KEY,
    RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_BUDGET_MAX_TOKENS,
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
)
from eneo.flows.flow_document_limits import FLOW_DOCUMENT_RENDER_HARD_LIMITS
from eneo.flows.flow_input_limits import (
    FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
    FLOW_INPUT_MAX_FILES_COUNT,
    FLOW_INPUT_MAX_LIMIT_BYTES,
    FLOW_INPUT_MIN_LIMIT_BYTES,
)
from eneo.flows.runtime.document_rendering.limits import DocumentRenderLimits
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
    # Read-only: whether signed file-reference URLs can be minted (a reference
    # base URL or public origin is configured). Gates UI that only makes sense
    # with them (e.g. the assistant inline-file-text toggle). Computed from
    # deployment config, never persisted.
    file_references_enabled: bool = False
    # Read-only: whether an object-store connection is configured for this
    # deployment. Gates UI that only works with S3-backed originals (the
    # assistant inline-file-text toggle). Distinct from object_content_enabled,
    # which only reports that the object-content module started.
    object_store_configured: bool = False
    # Read-only: whether an external transcription service is configured for
    # flow audio steps. Gates flow authoring UI for options only that service
    # honours (speaker identification). Computed from deployment config, never
    # persisted.
    flow_transcription_service_configured: bool = False
    # Read-only: how the external service is used ("full" or "diarize"), None
    # when it is not configured. In "diarize" mode the flow's own transcription
    # model still transcribes, so the model picker stays meaningful.
    flow_transcription_service_mode: Literal["full", "diarize"] | None = None
    # Read-only: whether the guarded SharePoint fixture API is available in
    # this deployment. Lets the UI expose local test controls without relying
    # on a manually entered query parameter.
    sharepoint_fixture_mode_available: bool = False


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
    "file_max_size_ceiling_bytes": 52428800,
    "audio_max_size_ceiling_bytes": 209715200,
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

FLOW_MAPPED_EXECUTION_POLICY_EXAMPLE: JsonDict = {
    "version": 1,
    "max_provider_calls_per_mapped_step": 20,
    "max_estimated_input_tokens_per_mapped_step": 200000,
    "max_provider_calls_source": "organization",
    "deployment_default_max_provider_calls": 100,
}

FLOW_MAPPED_EXECUTION_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "max_provider_calls_per_mapped_step": 20,
    "max_estimated_input_tokens_per_mapped_step": None,
}

FLOW_RAG_EVIDENCE_POLICY_EXAMPLE: JsonDict = {
    "version": 1,
    "max_sources_with_recorded_passages": 25,
    "max_recorded_passages_per_source": 30,
    "max_recorded_passage_bytes": 4096,
    "max_recorded_passage_bytes_per_step": 131072,
    "max_recorded_passage_bytes_per_run_view": 2097152,
}

FLOW_RAG_EVIDENCE_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "max_sources_with_recorded_passages": 50,
    "max_recorded_passage_bytes": 8192,
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

FlowEvidencePolicyUpdateFlag = bool | SkipJsonSchema[None]


def _strip_json_schema_default(schema: JsonDict) -> None:
    schema.pop("default", None)


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
    audio_max_files_per_run: int = Field(
        ge=1,
        le=FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
        description=(
            "Effective tenant-level audio file count ceiling for each Flow run. "
            "Resetting the stored override to null restores the default; this "
            "response always returns the resolved positive integer."
        ),
    )
    file_max_size_ceiling_bytes: int = Field(
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        description=(
            "Effective writable ceiling for file uploads: the deployment "
            "upload-admission limit capped by the flow-input hard maximum. "
            "Tenant values above it are rejected on write and clamped on read."
        ),
    )
    audio_max_size_ceiling_bytes: int = Field(
        ge=FLOW_INPUT_MIN_LIMIT_BYTES,
        description=(
            "Effective writable ceiling for audio uploads: the deployment "
            "upload-admission limit capped by the flow-input hard maximum. "
            "Tenant values above it are rejected on write and clamped on read."
        ),
    )


class FlowInputLimitsUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_INPUT_LIMITS_UPDATE_EXAMPLE},
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
        extra="forbid",
        json_schema_extra={"example": FLOW_DOCUMENT_RENDER_LIMITS_UPDATE_EXAMPLE},
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
        extra="forbid",
        json_schema_extra={"example": FLOW_RUNTIME_POLICY_UPDATE_EXAMPLE},
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


class FlowMappedExecutionPolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_MAPPED_EXECUTION_POLICY_EXAMPLE}
    )

    version: Literal[1] = Field(
        default=1,
        description="Mapped execution policy schema version.",
    )
    max_provider_calls_per_mapped_step: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Resolved maximum provider calls for one mapped step attempt, "
            "including one reserved native-JSON fallback call (N calls admit "
            "at most N-1 mapped items). Reflects the organization ceiling "
            "when configured, otherwise the deployment default. Null means "
            "mapped authoring is disabled — by an explicit organization "
            "opt-out, an unset deployment default, or invalid stored state."
        ),
    )
    max_estimated_input_tokens_per_mapped_step: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Maximum estimated packaged input tokens across one mapped step attempt. "
            "Null means no aggregate tenant token ceiling is configured."
        ),
    )
    max_provider_calls_source: Literal[
        "deployment_default", "organization", "organization_disabled", "invalid"
    ] = Field(
        description=(
            "Where the resolved call ceiling comes from: the deployment "
            "default (nothing configured), an organization-configured "
            "ceiling, an explicit organization opt-out, or invalid stored "
            "state that fails closed until an administrator saves a value or "
            "restores the default."
        ),
    )
    deployment_default_max_provider_calls: int | None = Field(
        ge=2,
        description=(
            "The deployment-wide fallback call ceiling that applies while the "
            "organization has not configured its own value. Null when the "
            "deployment ships with mapped authoring disabled."
        ),
    )


class FlowMappedExecutionPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_MAPPED_EXECUTION_POLICY_UPDATE_EXAMPLE},
    )

    max_provider_calls_per_mapped_step: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Set a tenant provider-call ceiling of at least 2 (one call is "
            "reserved for a possible native-JSON fallback), or send null to "
            "explicitly disable new mapped authoring for the organization. "
            "Omit the field to leave the stored policy unchanged. An "
            "organization that never configured a ceiling inherits the "
            "deployment default; use restore_max_provider_calls_default to "
            "return to that inherited state."
        ),
    )
    max_estimated_input_tokens_per_mapped_step: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Set a positive aggregate estimated-input-token ceiling, or send null to "
            "remove it."
        ),
    )
    restore_max_provider_calls_default: bool = Field(
        default=False,
        description=(
            "Remove the organization's stored call ceiling (or opt-out) so the "
            "deployment default applies again. Mutually exclusive with "
            "max_provider_calls_per_mapped_step."
        ),
    )


class FlowRagEvidencePolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RAG_EVIDENCE_POLICY_EXAMPLE}
    )

    version: Literal[1] = Field(
        default=1,
        description="Knowledge evidence policy schema version.",
    )
    max_sources_with_recorded_passages: int = Field(
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_SOURCES_KEY],
        description=(
            "How many retrieved sources record passage text. Every retrieved "
            "source is always listed with its identity; only passage detail is "
            "bounded."
        ),
    )
    max_recorded_passages_per_source: int = Field(
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY],
        description="How many passages one source records, highest score first.",
    )
    max_recorded_passage_bytes: int = Field(
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY],
        description=(
            "Byte ceiling for one recorded passage. A longer passage keeps its "
            "leading bytes and reports the dropped tail."
        ),
    )
    max_recorded_passage_bytes_per_step: int = Field(
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY],
        description="Total recorded passage bytes one step attempt may hold.",
    )
    max_recorded_passage_bytes_per_run_view: int = Field(
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY],
        description=(
            "Total recorded passage bytes one interactive run view may show. A "
            "run has no attempt limit, so this bounds what reading a run with "
            "many attempts materialises. Sources and counts are never released."
        ),
    )


class FlowRagEvidencePolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RAG_EVIDENCE_POLICY_UPDATE_EXAMPLE},
    )

    max_sources_with_recorded_passages: int | None = Field(
        default=None,
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_SOURCES_KEY],
        description="Set the source ceiling, or send null to restore the default.",
    )
    max_recorded_passages_per_source: int | None = Field(
        default=None,
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY],
        description="Set the per-source ceiling, or send null to restore the default.",
    )
    max_recorded_passage_bytes: int | None = Field(
        default=None,
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY],
        description="Set the per-passage ceiling, or send null to restore the default.",
    )
    max_recorded_passage_bytes_per_step: int | None = Field(
        default=None,
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY],
        description="Set the per-step ceiling, or send null to restore the default.",
    )
    max_recorded_passage_bytes_per_run_view: int | None = Field(
        default=None,
        ge=1,
        le=RAG_EVIDENCE_CEILINGS[RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY],
        description="Set the per-run-view ceiling, or send null to restore the default.",
    )


class AIBuilderBudgetSettingsPublic(BaseModel):
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    max_attachments: int
    max_message_chars: int
    max_template_inspection_uncompressed_bytes: int
    max_template_placeholders: int
    max_attachments_hard_limit: int
    max_message_chars_hard_limit: int
    max_template_inspection_uncompressed_bytes_hard_limit: int
    max_template_placeholders_hard_limit: int
    max_template_archive_entries_per_file_hard_limit: int
    max_template_uncompressed_bytes_per_file_hard_limit: int
    max_planning_state_payload_bytes_hard_limit: int
    budget_token_hard_limit: int


class AIBuilderBudgetSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_safety_buffer_tokens: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_BUDGET_MAX_TOKENS,
    )
    minimum_conversation_budget_tokens: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_BUDGET_MAX_TOKENS,
    )
    max_attachments: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    )
    max_message_chars: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    )
    max_template_inspection_uncompressed_bytes: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
    )
    max_template_placeholders: int | None = Field(
        default=None,
        ge=1,
        le=AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
    )


class FlowEvidencePolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_EVIDENCE_POLICY_EXAMPLE}
    )

    allow_sensitive_flow_exports: bool = False
    allow_space_admin_raw_export_class3: bool = False
    allow_run_owner_raw_export_class3: bool = False
    allow_service_key_raw_export_class3: bool = False


class FlowEvidencePolicyUpdate(BaseModel):
    """Omit fields to keep them unchanged; explicit null is not a policy value."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_EVIDENCE_POLICY_UPDATE_EXAMPLE},
    )

    allow_sensitive_flow_exports: FlowEvidencePolicyUpdateFlag = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )
    allow_space_admin_raw_export_class3: FlowEvidencePolicyUpdateFlag = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )
    allow_run_owner_raw_export_class3: FlowEvidencePolicyUpdateFlag = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )
    allow_service_key_raw_export_class3: FlowEvidencePolicyUpdateFlag = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )

    @field_validator(
        "allow_sensitive_flow_exports",
        "allow_space_admin_raw_export_class3",
        "allow_run_owner_raw_export_class3",
        "allow_service_key_raw_export_class3",
        mode="before",
    )
    @classmethod
    def reject_null_flags(cls, value: object) -> object:
        if value is None:
            raise ValueError(
                "Flow evidence policy flags must be true or false; omit fields to leave them unchanged."
            )
        return value


FLOW_DEBUG_EVIDENCE_ELIGIBILITY_DESCRIPTION = (
    "Tenant purge eligibility window for stored Flow debug evidence. Null means "
    "no tenant window; saving a value never redacts evidence."
)
FLOW_RUN_HISTORY_ELIGIBILITY_DESCRIPTION = (
    "Tenant purge eligibility fallback for Flow run history. A Flow value "
    "overrides its Space "
    "value, and a Space value overrides this tenant value."
)
FLOW_RUNTIME_UPLOAD_ELIGIBILITY_DESCRIPTION = (
    "Tenant purge eligibility window for Flow runtime uploads that were never "
    "bound to a run input. Null means no tenant window; saving a value never "
    "removes uploads."
)


class FlowRetentionPolicyPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "run_debug_evidence_days": 30,
                "flow_run_history_retention_days": 30,
                "flow_runtime_upload_abandonment_days": 14,
            }
        },
    )

    run_debug_evidence_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_DEBUG_EVIDENCE_ELIGIBILITY_DESCRIPTION,
    )
    flow_run_history_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_RUN_HISTORY_ELIGIBILITY_DESCRIPTION,
    )
    flow_runtime_upload_abandonment_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_RUNTIME_UPLOAD_ELIGIBILITY_DESCRIPTION,
    )


class FlowRetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "run_debug_evidence_days": 30,
                "flow_run_history_retention_days": 30,
                "flow_runtime_upload_abandonment_days": 14,
            }
        },
    )

    run_debug_evidence_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_DEBUG_EVIDENCE_ELIGIBILITY_DESCRIPTION,
        json_schema_extra=_strip_json_schema_default,
    )
    flow_run_history_retention_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_RUN_HISTORY_ELIGIBILITY_DESCRIPTION,
        json_schema_extra=_strip_json_schema_default,
    )
    flow_runtime_upload_abandonment_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=FLOW_RUNTIME_UPLOAD_ELIGIBILITY_DESCRIPTION,
        json_schema_extra=_strip_json_schema_default,
    )


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
    """Read-only policy allowance for one accessible completion model."""

    completion_model_id: UUID
    name: str
    nickname: str | None
    max_input_tokens: int
    supports_tool_calling: bool
    skill_context_token_allowance: int


class SkillRuntimeModelProjections(BaseModel):
    context_share_percent: int
    models: list[SkillRuntimeModelProjection]
