from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.config import JsonDict
from pydantic.json_schema import SkipJsonSchema

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.ai_models.embedding_models.embedding_model import EmbeddingModelPublicLegacy
from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.flows.flow_document_limits import FLOW_DOCUMENT_RENDER_HARD_LIMITS
from eneo.flows.flow_input_limits import (
    FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
    FLOW_INPUT_MAX_FILES_COUNT,
    FLOW_INPUT_MAX_LIMIT_BYTES,
    FLOW_INPUT_MIN_LIMIT_BYTES,
)
from eneo.flows.runtime.document_rendering.limits import DocumentRenderLimits
from eneo.main.models import InDB

if TYPE_CHECKING:
    from eneo.data_retention.infrastructure.data_retention_service import (
        FlowRetentionControlPlaneState,
        FlowRetentionDataImpact,
        FlowRetentionImpactPreview,
    )


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
    "flow_run_history_retention_days": 30,
    "flow_run_history_minimum_retention_days": 90,
    "flow_run_history_no_purge": False,
    "flow_runtime_upload_abandonment_days": 14,
    "effective_state": {
        "run_history_deletion_active": True,
        "runtime_upload_abandonment_active": True,
        "classification_policy_count": 0,
    },
}

FLOW_RETENTION_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "flow_run_history_retention_days": 30,
    "flow_run_history_minimum_retention_days": 90,
    "flow_run_history_no_purge": False,
}

FLOW_RETENTION_PREVIEW_EXAMPLE: JsonDict = {
    "destructive_change": True,
    "control_plane_version": "a" * 64,
    "preview_hash": "b" * 64,
    "previewed_at": "2026-07-13T12:00:00Z",
    "run_history_anchor": "finished_at_or_created_at",
    "runtime_upload_anchor": "created_at",
    "run_history": {
        "current_eligible_count": 0,
        "proposed_eligible_count": 12,
        "newly_eligible_count": 12,
        "no_longer_eligible_count": 0,
        "proposed_eligible_bytes": 4096,
        "newly_eligible_bytes": 4096,
        "earliest_proposed_anchor": "2025-01-01T12:00:00Z",
        "latest_proposed_anchor": "2026-01-01T12:00:00Z",
        "earliest_proposed_delete_after_at": "2025-01-31T12:00:00Z",
        "latest_proposed_delete_after_at": "2026-01-31T12:00:00Z",
        "earliest_proposed_minimum_not_before_at": "2025-04-01T12:00:00Z",
        "latest_proposed_minimum_not_before_at": "2026-04-01T12:00:00Z",
    },
    "runtime_uploads": {
        "current_eligible_count": 0,
        "proposed_eligible_count": 3,
        "newly_eligible_count": 3,
        "no_longer_eligible_count": 0,
        "proposed_eligible_bytes": 1024,
        "newly_eligible_bytes": 1024,
        "earliest_proposed_anchor": "2025-06-01T12:00:00Z",
        "latest_proposed_anchor": "2025-12-01T12:00:00Z",
        "earliest_proposed_delete_after_at": "2025-06-15T12:00:00Z",
        "latest_proposed_delete_after_at": "2025-12-15T12:00:00Z",
        "earliest_proposed_minimum_not_before_at": "2025-08-30T12:00:00Z",
        "latest_proposed_minimum_not_before_at": "2026-03-01T12:00:00Z",
    },
    "lifecycle_blockers": {
        "undelivered_audit_count": 1,
        "unresolved_webhook_count": 0,
        "active_rerun_count": 0,
    },
    "policy_blockers": {
        "run_history_minimum_not_satisfied_count": 4,
        "run_history_no_purge_count": 0,
        "run_history_policy_conflict_count": 12,
        "runtime_upload_minimum_not_satisfied_count": 1,
        "runtime_upload_no_purge_count": 0,
        "runtime_upload_policy_conflict_count": 3,
    },
    "latent_space_retention_days": [7, 30],
    "latent_flow_retention_days": [1, 14],
}

FLOW_CLASSIFICATION_RETENTION_POLICY_EXAMPLE: JsonDict = {
    "security_classification_id": "6f982fa9-8f74-451f-b6fc-773f937af7ef",
    "data_retention_days": 7,
    "minimum_retention_days": 30,
    "no_purge": False,
}

FLOW_CLASSIFICATION_RETENTION_POLICIES_EXAMPLE: JsonDict = {
    "policies": [FLOW_CLASSIFICATION_RETENTION_POLICY_EXAMPLE],
}

FLOW_CLASSIFICATION_RETENTION_POLICY_UPDATE_EXAMPLE: JsonDict = {
    "data_retention_days": 14,
    "minimum_retention_days": 30,
    "no_purge": False,
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
    audio_max_files_per_run: int | None = Field(
        ...,
        ge=1,
        le=FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
        description="Null means no tenant-level audio file count ceiling.",
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


class FlowRetentionEffectiveStatePublic(BaseModel):
    run_history_deletion_active: bool = Field(
        description=(
            "Whether an organization policy or at least one classification policy "
            "can activate automatic Flow run-history deletion."
        )
    )
    runtime_upload_abandonment_active: bool = Field(
        description="Whether automatic abandoned runtime-upload deletion is active."
    )
    classification_policy_count: int = Field(
        ge=0,
        description="Number of configured classification activation policies.",
    )

    @classmethod
    def from_domain(
        cls,
        state: "FlowRetentionControlPlaneState",
    ) -> "FlowRetentionEffectiveStatePublic":
        return cls(
            run_history_deletion_active=(
                state.organization_run_history_days is not None
                or any(
                    policy.data_retention_days is not None
                    for policy in state.classification_policies
                )
            ),
            runtime_upload_abandonment_active=(
                state.runtime_upload_abandonment_days is not None
            ),
            classification_policy_count=len(state.classification_policies),
        )


class FlowRetentionChangeConfirmationPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_control_plane_version: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_preview_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    previewed_at: datetime


class FlowRetentionDataImpactPublic(BaseModel):
    current_eligible_count: int = Field(ge=0)
    proposed_eligible_count: int = Field(ge=0)
    newly_eligible_count: int = Field(ge=0)
    no_longer_eligible_count: int = Field(ge=0)
    proposed_eligible_bytes: int = Field(ge=0)
    newly_eligible_bytes: int = Field(ge=0)
    earliest_proposed_anchor: datetime | None
    latest_proposed_anchor: datetime | None
    earliest_proposed_delete_after_at: datetime | None
    latest_proposed_delete_after_at: datetime | None
    earliest_proposed_minimum_not_before_at: datetime | None
    latest_proposed_minimum_not_before_at: datetime | None

    @classmethod
    def from_domain(
        cls,
        impact: "FlowRetentionDataImpact",
    ) -> "FlowRetentionDataImpactPublic":
        return cls(
            current_eligible_count=impact.current_eligible_count,
            proposed_eligible_count=impact.proposed_eligible_count,
            newly_eligible_count=impact.newly_eligible_count,
            no_longer_eligible_count=impact.no_longer_eligible_count,
            proposed_eligible_bytes=impact.proposed_eligible_bytes,
            newly_eligible_bytes=impact.newly_eligible_bytes,
            earliest_proposed_anchor=impact.earliest_proposed_anchor,
            latest_proposed_anchor=impact.latest_proposed_anchor,
            earliest_proposed_delete_after_at=(
                impact.earliest_proposed_delete_after_at
            ),
            latest_proposed_delete_after_at=impact.latest_proposed_delete_after_at,
            earliest_proposed_minimum_not_before_at=(
                impact.earliest_proposed_minimum_not_before_at
            ),
            latest_proposed_minimum_not_before_at=(
                impact.latest_proposed_minimum_not_before_at
            ),
        )


class FlowRetentionLifecycleBlockersPublic(BaseModel):
    undelivered_audit_count: int = Field(ge=0)
    unresolved_webhook_count: int = Field(ge=0)
    active_rerun_count: int = Field(ge=0)


class FlowRetentionPolicyBlockersPublic(BaseModel):
    run_history_minimum_not_satisfied_count: int = Field(ge=0)
    run_history_no_purge_count: int = Field(ge=0)
    run_history_policy_conflict_count: int = Field(ge=0)
    runtime_upload_minimum_not_satisfied_count: int = Field(ge=0)
    runtime_upload_no_purge_count: int = Field(ge=0)
    runtime_upload_policy_conflict_count: int = Field(ge=0)


class FlowRetentionImpactPreviewPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RETENTION_PREVIEW_EXAMPLE}
    )

    destructive_change: bool
    control_plane_version: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    preview_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    previewed_at: datetime
    run_history_anchor: Literal["finished_at_or_created_at"]
    runtime_upload_anchor: Literal["created_at"]
    run_history: FlowRetentionDataImpactPublic
    runtime_uploads: FlowRetentionDataImpactPublic
    lifecycle_blockers: FlowRetentionLifecycleBlockersPublic
    policy_blockers: FlowRetentionPolicyBlockersPublic
    latent_space_retention_days: list[int]
    latent_flow_retention_days: list[int]

    @classmethod
    def from_domain(
        cls,
        preview: "FlowRetentionImpactPreview",
    ) -> "FlowRetentionImpactPreviewPublic":
        return cls(
            destructive_change=preview.destructive_change,
            control_plane_version=preview.control_plane_version,
            preview_hash=preview.preview_hash,
            previewed_at=preview.previewed_at,
            run_history_anchor="finished_at_or_created_at",
            runtime_upload_anchor="created_at",
            run_history=FlowRetentionDataImpactPublic.from_domain(preview.run_history),
            runtime_uploads=FlowRetentionDataImpactPublic.from_domain(
                preview.runtime_uploads
            ),
            lifecycle_blockers=FlowRetentionLifecycleBlockersPublic(
                undelivered_audit_count=(
                    preview.lifecycle_blockers.undelivered_audit_count
                ),
                unresolved_webhook_count=(
                    preview.lifecycle_blockers.unresolved_webhook_count
                ),
                active_rerun_count=preview.lifecycle_blockers.active_rerun_count,
            ),
            policy_blockers=FlowRetentionPolicyBlockersPublic(
                **preview.policy_blockers.hash_payload()
            ),
            latent_space_retention_days=list(preview.latent_space_retention_days),
            latent_flow_retention_days=list(preview.latent_flow_retention_days),
        )


class FlowRetentionOrganizationPreviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "flow_run_history_retention_days": 30,
                "flow_run_history_minimum_retention_days": 90,
                "flow_run_history_no_purge": False,
                "flow_runtime_upload_abandonment_days": 14,
            }
        },
    )

    flow_run_history_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Organization Flow run-history activation window. Null leaves automatic "
            "deletion off except for spaces with a matching classification policy."
        ),
    )
    flow_runtime_upload_abandonment_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
    )
    flow_run_history_minimum_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Organization minimum retention barrier for Flow run history and "
            "never-attached runtime uploads. Null removes this barrier."
        ),
    )
    flow_run_history_no_purge: bool = Field(
        ...,
        strict=True,
        description=(
            "Organization barrier that blocks automatic Flow run-history and "
            "never-attached runtime-upload purge without activating deletion."
        ),
    )


class FlowClassificationRetentionPolicyPreviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_CLASSIFICATION_RETENTION_POLICY_UPDATE_EXAMPLE
        },
    )

    data_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Proposed matching-classification Flow run-history activation window."
        ),
    )
    minimum_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description="Proposed matching-classification minimum retention barrier.",
    )
    no_purge: bool = Field(
        ...,
        strict=True,
        description=(
            "Proposed matching-classification no-purge barrier; it does not "
            "activate automatic deletion."
        ),
    )


class FlowRetentionPolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RETENTION_POLICY_EXAMPLE}
    )

    run_debug_evidence_days: int | None = Field(...)
    flow_run_history_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Organization Flow run-history activation window. Null leaves automatic "
            "deletion off except for spaces with a matching classification policy."
        ),
    )
    flow_runtime_upload_abandonment_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
    )
    flow_run_history_minimum_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
    )
    flow_run_history_no_purge: bool = Field(..., strict=True)
    effective_state: FlowRetentionEffectiveStatePublic


class FlowRetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RETENTION_POLICY_UPDATE_EXAMPLE},
    )

    run_debug_evidence_days: int | None = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )
    flow_run_history_retention_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Organization Flow run-history activation window. Null leaves automatic "
            "deletion off except for spaces with a matching classification policy."
        ),
        json_schema_extra=_strip_json_schema_default,
    )
    flow_runtime_upload_abandonment_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        json_schema_extra=_strip_json_schema_default,
    )
    flow_run_history_minimum_retention_days: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        json_schema_extra=_strip_json_schema_default,
    )
    flow_run_history_no_purge: bool = Field(
        default=False,
        strict=True,
        json_schema_extra=_strip_json_schema_default,
    )
    confirmation: FlowRetentionChangeConfirmationPublic | None = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )


class FlowClassificationRetentionPolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_CLASSIFICATION_RETENTION_POLICY_EXAMPLE}
    )

    security_classification_id: UUID
    data_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Matching-classification Flow run-history activation window in days. "
            "The effective window is the minimum of this value, the organization "
            "value, and configured Space or Flow tightening values."
        ),
    )
    minimum_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description="Matching-classification minimum retention barrier in days.",
    )
    no_purge: bool = Field(
        ...,
        strict=True,
        description=(
            "Matching-classification no-purge barrier; it never activates deletion."
        ),
    )


class FlowClassificationRetentionPoliciesPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_CLASSIFICATION_RETENTION_POLICIES_EXAMPLE}
    )

    policies: list[FlowClassificationRetentionPolicyPublic]


class FlowClassificationRetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_CLASSIFICATION_RETENTION_POLICY_UPDATE_EXAMPLE
        },
    )

    data_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description=(
            "Matching-classification Flow run-history activation window in days. "
            "The effective window is the minimum of this value, the organization "
            "value, and configured Space or Flow tightening values."
        ),
    )
    minimum_retention_days: int | None = Field(
        ...,
        strict=True,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
        description="Matching-classification minimum retention barrier in days.",
    )
    no_purge: bool = Field(
        ...,
        strict=True,
        description=(
            "Matching-classification no-purge barrier; it never activates deletion."
        ),
    )
    confirmation: FlowRetentionChangeConfirmationPublic | None = Field(
        default=None,
        json_schema_extra=_strip_json_schema_default,
    )
