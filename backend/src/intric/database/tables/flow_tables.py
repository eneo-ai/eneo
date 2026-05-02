from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import (
    BaseCrossReference,
    BasePublic,
    BaseWithTableName,
)
from intric.database.tables.files_table import Files
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
)

FLOW_STEP_INPUT_SOURCE_VALUES = tuple(item.value for item in FlowInputSource)
FLOW_STEP_INPUT_TYPE_VALUES = tuple(item.value for item in FlowInputType)
FLOW_STEP_OUTPUT_MODE_VALUES = tuple(item.value for item in FlowOutputMode)
FLOW_STEP_OUTPUT_TYPE_VALUES = tuple(item.value for item in FlowOutputType)
FLOW_STEP_MCP_POLICY_VALUES = tuple(item.value for item in FlowMcpPolicy)
FLOW_RUN_STATUS_VALUES = tuple(item.value for item in FlowRunStatus)
FLOW_RUN_RERUN_OPERATION_STATUS_VALUES = tuple(
    item.value for item in FlowRunRerunOperationStatus
)
FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES = tuple(
    item.value for item in FlowRunRerunInvalidationRole
)
FLOW_RUN_LIFECYCLE_SOURCE_VALUES = tuple(item.value for item in FlowRunLifecycleSource)
FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES = tuple(
    item.value for item in FlowRunReviewCheckpointState
)
FLOW_RUN_ACTIVE_REVIEW_CHECKPOINT_STATE_VALUES = (
    FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
    FlowRunReviewCheckpointState.EDITED.value,
    FlowRunReviewCheckpointState.APPROVED.value,
)
FLOW_RUN_AUDIT_TARGET_STATUS_VALUES = tuple(
    dict.fromkeys(
        (
            FlowRunStatus.COMPLETED.value,
            FlowRunStatus.FAILED.value,
            FlowRunStatus.CANCELLED.value,
            *FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES,
        )
    )
)
FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES = (
    "pending",
    "delivered",
    "dead_lettered",
)
FLOW_STEP_RESULT_STATUS_VALUES = tuple(item.value for item in FlowStepResultStatus)
FLOW_STEP_ATTEMPT_STATUS_VALUES = tuple(item.value for item in FlowStepAttemptStatus)
FLOW_RUN_STEP_RESULT_FILE_SOURCE_VALUES = ("generated_output", "declared_artifact")
MODULE_HEALTH_STATUS_VALUES = ("healthy", "unhealthy", "unknown")
MODULE_COMPAT_STATUS_VALUES = ("compatible", "incompatible", "unknown")
FLOW_TEMPLATE_ASSET_STATUS_VALUES = tuple(
    item.value for item in FlowTemplateAssetStatus
)


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class Flows(BasePublic):
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    published_version: Mapped[Optional[int]] = mapped_column(nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    data_retention_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    draft_revision: Mapped[int] = mapped_column(nullable=False, server_default="0")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_flows_id_tenant_id"),
        # W13: active flow names are unique per space.
        Index(
            "uq_flows_space_id_name_active",
            "space_id",
            "name",
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        Index("ix_flows_space_deleted", "space_id", "deleted_at"),
    )


class FlowSteps(BasePublic):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="RESTRICT"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    user_description: Mapped[Optional[str]] = mapped_column(nullable=True)
    input_source: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        server_default="flow_input",
    )
    input_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="any",
    )
    input_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_mode: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pass_through",
    )
    output_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="text",
    )
    output_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    input_bindings: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_classification_override: Mapped[Optional[int]] = mapped_column(nullable=True)
    mcp_policy: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="inherit",
    )
    input_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    output_config: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    review_policy: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    __table_args__ = (
        UniqueConstraint("flow_id", "step_order", name="uq_flow_steps_flow_step_order"),
        UniqueConstraint("flow_id", "id", name="uq_flow_steps_flow_id_id"),
        UniqueConstraint("id", "tenant_id", name="uq_flow_steps_id_tenant_id"),
        CheckConstraint(
            "input_source IN ('flow_input','previous_step','all_previous_steps','http_get','http_post')",
            name="ck_flow_steps_input_source",
        ),
        CheckConstraint(
            "input_type IN ('text','json','image','audio','document','file','any')",
            name="ck_flow_steps_input_type",
        ),
        CheckConstraint(
            "output_mode IN ('pass_through','http_post','transcribe_only','template_fill')",
            name="ck_flow_steps_output_mode",
        ),
        CheckConstraint(
            "output_type IN ('text','json','pdf','docx')",
            name="ck_flow_steps_output_type",
        ),
        CheckConstraint(
            "mcp_policy IN ('inherit','restricted')", name="ck_flow_steps_mcp_policy"
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_steps_flow_tenant",
        ),
    )


class FlowStepDependencies(BaseCrossReference):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        primary_key=True,
    )
    parent_step_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="CASCADE"),
        primary_key=True,
    )
    child_step_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "parent_step_id <> child_step_id",
            name="ck_flow_step_dependencies_no_self_ref",
        ),
        ForeignKeyConstraint(
            ["flow_id", "parent_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_parent_same_flow",
        ),
        ForeignKeyConstraint(
            ["flow_id", "child_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_child_same_flow",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_flow_tenant",
        ),
    )


class FlowVersions(BaseCrossReference):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    definition_checksum: Mapped[str] = mapped_column(nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_versions_flow_tenant",
        ),
        UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )


class FlowTemplateAssets(BasePublic):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(nullable=False)
    mimetype: Mapped[Optional[str]] = mapped_column(nullable=True)
    placeholders: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="ready",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "id", "tenant_id", name="uq_flow_template_assets_id_tenant_id"
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_template_assets_flow_tenant",
        ),
        CheckConstraint(
            "status IN ('ready','needs_action','read_only','unavailable')",
            name="ck_flow_template_assets_status",
        ),
        Index(
            "ix_flow_template_assets_flow_active",
            "flow_id",
            "updated_at",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )


class FlowRuns(BasePublic):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_version: Mapped[int] = mapped_column(nullable=False)
    principal_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="user",
    )
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT"),
        nullable=True,
    )
    principal_api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="RESTRICT"),
        nullable=True,
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trace_id: Mapped[UUID] = mapped_column(default=uuid4, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    request_fingerprint: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(
        nullable=False,
        server_default="1",
        comment=(
            "Monotonic lifecycle token for rerun/resume compare-and-swap; "
            "updated_at is display metadata."
        ),
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        index=True,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "principal_type IN ('user','service_key')",
            name="ck_flow_runs_principal_type",
        ),
        CheckConstraint(
            "("
            "(principal_type = 'user' AND principal_user_id IS NOT NULL AND principal_api_key_id IS NULL) "
            "OR "
            "(principal_type = 'service_key' AND principal_user_id IS NULL AND principal_api_key_id IS NOT NULL)"
            ")",
            name="ck_flow_runs_principal_identity",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_RUN_STATUS_VALUES)})",
            name="ck_flow_runs_status",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_runs_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_id", "flow_version"],
            ["flow_versions.flow_id", "flow_versions.version"],
            ondelete="RESTRICT",
            name="fk_flow_runs_flow_version",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_flow_runs_id_tenant_id"),
        UniqueConstraint("id", "flow_id", name="uq_flow_runs_id_flow_id"),
        Index("ix_flow_runs_flow_id_status", "flow_id", "status"),
        Index("ix_flow_runs_tenant_created_at", "tenant_id", "created_at"),
        Index(
            "uq_flow_runs_idempotency_user_key",
            "tenant_id",
            "flow_id",
            "principal_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text(
                "principal_type = 'user' AND idempotency_key IS NOT NULL"
            ),
        ),
        Index(
            "uq_flow_runs_idempotency_service_key",
            "tenant_id",
            "flow_id",
            "principal_api_key_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text(
                "principal_type = 'service_key' AND idempotency_key IS NOT NULL"
            ),
        ),
        Index(
            "ix_flow_runs_running_updated_at",
            "status",
            "updated_at",
            postgresql_where=sa.text("status = 'running'"),
        ),
    )


class FlowStepResults(BasePublic):
    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="SET NULL"),
        nullable=True,
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL"),
        nullable=True,
    )
    current_attempt_no: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        server_default="1",
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    effective_prompt: Mapped[Optional[str]] = mapped_column(nullable=True)
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    model_parameters_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    num_tokens_input: Mapped[Optional[int]] = mapped_column(nullable=True)
    num_tokens_output: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
    )
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    flow_step_execution_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="ck_flow_step_results_status",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_results_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_step_results_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_step_results_run_step"
        ),
        Index(
            "ix_flow_step_results_run_flow_step", "flow_run_id", "flow_id", "step_id"
        ),
    )


class FlowRunRerunOperations(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_rerun_operations_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_rerun_operations_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    rerun_step_id: Mapped[UUID] = mapped_column(nullable=False)
    rerun_step_order: Mapped[int] = mapped_column(nullable=False)
    root_attempt_no: Mapped[int] = mapped_column(nullable=False)
    root_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_rerun_operations_root_attempt",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowRunRerunOperationStatus.QUEUED.value,
    )
    request_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expected_run_revision: Mapped[int] = mapped_column(nullable=False)
    accepted_run_revision: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    step_inputs_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    requested_by_principal_type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="RESTRICT",
            name="fk_rerun_operations_requested_by_user",
        ),
        nullable=False,
    )
    failure_code: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_check_values(FLOW_RUN_RERUN_OPERATION_STATUS_VALUES)})",
            name="ck_flow_run_rerun_operations_status",
        ),
        CheckConstraint(
            "requested_by_principal_type = 'user'",
            name="ck_flow_run_rerun_operations_user_principal",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_operations_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_operations_run_flow",
        ),
        UniqueConstraint(
            "tenant_id",
            "flow_run_id",
            "request_fingerprint",
            name="uq_flow_run_rerun_operations_request_fingerprint",
        ),
        Index("ix_flow_run_rerun_operations_run_status", "flow_run_id", "status"),
        Index(
            "uq_flow_run_rerun_operations_one_active_per_run",
            "flow_run_id",
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_flow_run_rerun_operations_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_flow_run_rerun_operations_run_step",
            "flow_run_id",
            "rerun_step_id",
        ),
    )


class FlowStepAttempts(BasePublic):
    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="SET NULL"),
        nullable=True,
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    rerun_operation_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowRunRerunOperations.id,
            ondelete="SET NULL",
            name="fk_step_attempts_rerun_operation",
        ),
        nullable=True,
    )
    predecessor_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_step_attempts_predecessor",
        ),
        nullable=True,
    )
    superseded_by_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_step_attempts_superseded_by",
        ),
        nullable=True,
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    requested_model: Mapped[Optional[str]] = mapped_column(nullable=True)
    response_model: Mapped[Optional[str]] = mapped_column(nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(nullable=True)
    finish_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    provider_response_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    num_tokens_input: Mapped[Optional[int]] = mapped_column(nullable=True)
    num_tokens_output: Mapped[Optional[int]] = mapped_column(nullable=True)
    provenance_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    flow_step_execution_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('started','retried','failed','completed','cancelled')",
            name="ck_flow_step_attempts_status",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_attempts_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_step_attempts_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_attempts_run_step_attempt",
        ),
        Index(
            "ix_flow_step_attempts_run_flow_step_attempt",
            "flow_run_id",
            "flow_id",
            "step_id",
            "attempt_no",
        ),
        Index("ix_flow_step_attempts_rerun_operation", "rerun_operation_id"),
        Index("ix_flow_step_attempts_predecessor_attempt", "predecessor_attempt_id"),
        Index(
            "ix_flow_step_attempts_superseded_by_attempt",
            "superseded_by_attempt_id",
        ),
    )


class FlowRunRerunInvalidatedSteps(BasePublic):
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            FlowRunRerunOperations.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_operation",
        ),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    invalidation_order: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    dependency_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    prior_step_result_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepResults.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_prior_result",
        ),
        nullable=True,
    )
    prior_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepAttempts.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_prior_attempt",
        ),
        nullable=True,
    )
    new_attempt_no: Mapped[Optional[int]] = mapped_column(nullable=True)
    new_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepAttempts.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_new_attempt",
        ),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            f"role IN ({_check_values(FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES)})",
            name="ck_flow_run_rerun_invalidated_steps_role",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_invalidated_steps_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_invalidated_steps_run_flow",
        ),
        UniqueConstraint(
            "operation_id",
            "step_id",
            name="uq_flow_run_rerun_invalidated_steps_operation_step",
        ),
        UniqueConstraint(
            "operation_id",
            "invalidation_order",
            name="uq_flow_run_rerun_invalidated_steps_operation_order",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_run_step",
            "flow_run_id",
            "step_id",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_prior_attempt",
            "prior_attempt_id",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_new_attempt",
            "new_attempt_id",
        ),
    )


class FlowRunReviewCheckpoints(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_review_checkpoints_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_review_checkpoints_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
    )
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")
    schema_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    original_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    current_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    requester_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="SET NULL",
            name="fk_review_checkpoints_requester_user",
        ),
        nullable=True,
    )
    requester_principal_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
    )
    decided_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="SET NULL",
            name="fk_review_checkpoints_decided_by_user",
        ),
        nullable=True,
    )
    decided_by_principal_type: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    next_step_ids_json: Mapped[Optional[list[str]]] = mapped_column(
        JSONB, nullable=True
    )
    resume_idempotency_key: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    resumed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            f"state IN ({_check_values(FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES)})",
            name="ck_flow_run_review_checkpoints_state",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_flow_run_review_checkpoints_revision",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_flow_run_review_checkpoints_schema_version",
        ),
        CheckConstraint(
            "requester_principal_type IN ('user','service_key')",
            name="ck_flow_run_review_checkpoints_requester_principal",
        ),
        CheckConstraint(
            "decided_by_principal_type IS NULL "
            "OR decided_by_principal_type IN ('user','service_key')",
            name="ck_flow_run_review_checkpoints_decider_principal",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_run_review_checkpoints_run_step_attempt",
        ),
        Index(
            "uq_flow_run_review_checkpoints_one_active_per_run",
            "flow_run_id",
            unique=True,
            postgresql_where=sa.text(
                "state IN ('awaiting_review', 'edited', 'approved')"
            ),
        ),
        Index(
            "uq_flow_run_review_checkpoints_resume_key",
            "tenant_id",
            "flow_run_id",
            "resume_idempotency_key",
            unique=True,
            postgresql_where=sa.text("resume_idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_flow_run_review_checkpoints_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_review_checkpoints_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
    )


class FlowRunStepInputFiles(BasePublic):
    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_input_files_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_input_files_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_input_files_run_step_attempt_file",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_input_files_run_step_attempt_ordinal",
        ),
        Index(
            "ix_flow_run_step_input_files_tenant_file",
            "tenant_id",
            "file_id",
        ),
        Index(
            "ix_flow_run_step_input_files_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_step_input_files_flow_step",
            "flow_id",
            "step_id",
        ),
    )


class FlowRunStepResultFiles(BasePublic):
    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_result_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowStepResults.id, ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"source IN ({_check_values(FLOW_RUN_STEP_RESULT_FILE_SOURCE_VALUES)})",
            name="ck_flow_run_step_result_files_source",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_result_files_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_result_files_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_result_files_run_step_attempt_file",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_result_files_run_step_attempt_ordinal",
        ),
        Index(
            "ix_flow_run_step_result_files_tenant_file",
            "tenant_id",
            "file_id",
        ),
        Index(
            "ix_flow_run_step_result_files_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_step_result_files_step_result",
            "step_result_id",
        ),
    )


class FlowRunAuditOutbox(BasePublic):
    """The row id is reused as the delivered audit log id."""

    __tablename__ = "flow_run_audit_outbox"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    run_revision: Mapped[int] = mapped_column(
        nullable=False,
        server_default="1",
    )
    review_checkpoint_id: Mapped[Optional[UUID]] = mapped_column(
        nullable=True,
        index=True,
    )
    checkpoint_revision: Mapped[Optional[int]] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    delivery_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
    )
    delivery_attempts: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
    )
    next_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
        server_default=sa.func.now(),
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    dead_lettered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    delivery_last_error: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)

    __table_args__ = (
        Index(
            "uq_flow_run_audit_outbox_run_revision",
            "flow_run_id",
            "run_revision",
            unique=True,
            postgresql_where=sa.text("review_checkpoint_id IS NULL"),
        ),
        Index(
            "uq_flow_run_audit_outbox_checkpoint_revision",
            "review_checkpoint_id",
            "checkpoint_revision",
            unique=True,
            postgresql_where=sa.text("review_checkpoint_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_run_flow",
        ),
        ForeignKeyConstraint(
            ["review_checkpoint_id"],
            ["flow_run_review_checkpoints.id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_review_checkpoint",
        ),
        CheckConstraint(
            f"target_status IN ({_check_values(FLOW_RUN_AUDIT_TARGET_STATUS_VALUES)})",
            name="ck_flow_run_audit_outbox_target_status",
        ),
        CheckConstraint(
            "("
            "(review_checkpoint_id IS NULL AND checkpoint_revision IS NULL) "
            "OR "
            "(review_checkpoint_id IS NOT NULL AND checkpoint_revision IS NOT NULL)"
            ")",
            name="ck_flow_run_audit_outbox_checkpoint_key",
        ),
        CheckConstraint(
            "description = action || ':' || source",
            name="ck_flow_run_audit_outbox_description",
        ),
        CheckConstraint(
            f"source IN ({_check_values(FLOW_RUN_LIFECYCLE_SOURCE_VALUES)})",
            name="ck_flow_run_audit_outbox_source",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_flow_run_audit_outbox_delivery_attempts",
        ),
        CheckConstraint(
            "delivery_status IN "
            f"({_check_values(FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES)})",
            name="ck_flow_run_audit_outbox_delivery_status",
        ),
        CheckConstraint(
            "("
            "(delivery_status = 'pending' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'delivered' "
            "AND delivered_at IS NOT NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'dead_lettered' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NOT NULL)"
            ")",
            name="ck_flow_run_audit_outbox_delivery_timestamps",
        ),
        Index("ix_flow_run_audit_outbox_tenant_created", "tenant_id", "created_at"),
        Index("ix_flow_run_audit_outbox_action", "action"),
        Index(
            "ix_flow_run_audit_outbox_pending_delivery",
            "next_delivery_at",
            "created_at",
            postgresql_where=sa.text("delivery_status = 'pending'"),
        ),
        Index(
            "ix_flow_run_audit_outbox_dead_lettered",
            "dead_lettered_at",
            postgresql_where=sa.text("delivery_status = 'dead_lettered'"),
        ),
    )


class ModuleRegistry(BasePublic):
    name: Mapped[str] = mapped_column(nullable=False)
    module_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    internal_url: Mapped[str] = mapped_column(nullable=False)
    health_endpoint: Mapped[str] = mapped_column(
        nullable=False, server_default="/health"
    )
    last_health_check_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True)
    )
    last_health_status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="unknown",
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    module_version: Mapped[Optional[str]] = mapped_column(nullable=True)
    image_digest: Mapped[Optional[str]] = mapped_column(nullable=True)
    module_api_contract: Mapped[Optional[str]] = mapped_column(nullable=True)
    core_compat_min: Mapped[Optional[str]] = mapped_column(nullable=True)
    core_compat_max: Mapped[Optional[str]] = mapped_column(nullable=True)
    compat_status: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="unknown",
    )
    release_notes_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "last_health_status IN ('healthy','unhealthy','unknown')",
            name="ck_module_registry_last_health_status",
        ),
        CheckConstraint(
            "compat_status IN ('compatible','incompatible','unknown')",
            name="ck_module_registry_compat_status",
        ),
    )


BUILDER_SESSION_STATUS_VALUES = (
    "chatting",
    "awaiting_approval",
    "applying",
    "applied",
    "cancelled",
)
BUILDER_PLAN_STATUS_VALUES = (
    "proposed",
    "approved",
    "applied",
    "rejected",
    "superseded",
)
BUILDER_TARGET_KIND_VALUES = ("create", "edit")


class BuilderSessions(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="chatting",
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )
    active_request_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    lock_token: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    lock_expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    latest_plan_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    planning_state_jsonb: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    planning_state_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default="0",
    )
    planning_phase: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    architecture_hash: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
        index=True,
    )
    planning_state_updated_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_builder_sessions_id_tenant_id"),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_sessions_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["latest_plan_id", "id"],
            ["builder_plans.id", "builder_plans.session_id"],
            name="fk_builder_sessions_latest_plan_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"target_kind IN ({','.join(repr(v) for v in BUILDER_TARGET_KIND_VALUES)})",
            name="ck_builder_sessions_target_kind",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_SESSION_STATUS_VALUES)})",
            name="ck_builder_sessions_status",
        ),
    )


class BuilderSessionFiles(BaseCrossReference):
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_session_files_session_tenant",
        ),
    )


class BuilderPlans(BasePublic):
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="proposed",
    )
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    spec_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    edit_result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_builder_plans_id_tenant_id"),
        UniqueConstraint("id", "session_id", name="uq_builder_plans_id_session_id"),
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_plans_session_tenant",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_PLAN_STATUS_VALUES)})",
            name="ck_builder_plans_status",
        ),
    )


class BuilderAttachmentObservations(BaseWithTableName):
    """Tenant-scoped cache of structured planning evidence per attachment.

    Composite natural key `(tenant_id, content_sha256, digest_version,
    fcm_version, pattern_registry_version)`: a bump to any version
    invalidates prior rows. `last_accessed_at` drives per-tenant LRU
    eviction; the tenant-prefixed index keeps eviction scans cheap.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
    )
    content_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    digest_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fcm_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    pattern_registry_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deterministic_signals_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )

    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "content_sha256",
            "digest_version",
            "fcm_version",
            "pattern_registry_version",
            name="pk_builder_attachment_observations",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_builder_attachment_obs_sha256_format",
        ),
        CheckConstraint(
            "digest_version > 0",
            name="ck_builder_attachment_obs_digest_version",
        ),
        CheckConstraint(
            "fcm_version > 0",
            name="ck_builder_attachment_obs_fcm_version",
        ),
        CheckConstraint(
            "pattern_registry_version > 0",
            name="ck_builder_attachment_obs_pattern_registry_version",
        ),
        Index(
            "ix_builder_attachment_obs_tenant_last_accessed",
            "tenant_id",
            "last_accessed_at",
        ),
    )
