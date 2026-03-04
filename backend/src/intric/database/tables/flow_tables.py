from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.job_table import Jobs
from intric.database.tables.mcp_server_table import MCPServerTools
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


FLOW_STEP_INPUT_SOURCE_VALUES = (
    "flow_input",
    "previous_step",
    "all_previous_steps",
    "http_get",
    "http_post",
)
FLOW_STEP_INPUT_TYPE_VALUES = ("text", "json", "image", "audio", "document", "file", "any")
FLOW_STEP_OUTPUT_MODE_VALUES = ("pass_through", "http_post")
FLOW_STEP_OUTPUT_TYPE_VALUES = ("text", "json", "pdf", "docx")
FLOW_STEP_MCP_POLICY_VALUES = ("inherit", "restricted")
FLOW_RUN_STATUS_VALUES = ("queued", "running", "completed", "failed", "cancelled")
FLOW_STEP_RESULT_STATUS_VALUES = ("pending", "running", "completed", "failed", "cancelled")
FLOW_STEP_ATTEMPT_STATUS_VALUES = ("started", "retried", "failed", "completed", "cancelled")
MODULE_HEALTH_STATUS_VALUES = ("healthy", "unhealthy", "unknown")
MODULE_COMPAT_STATUS_VALUES = ("compatible", "incompatible", "unknown")


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
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    data_retention_days: Mapped[Optional[int]] = mapped_column(nullable=True)
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
    input_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
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
    output_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    input_bindings: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    output_classification_override: Mapped[Optional[int]] = mapped_column(nullable=True)
    mcp_policy: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="inherit",
    )
    input_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    output_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("flow_id", "step_order", name="uq_flow_steps_flow_step_order"),
        UniqueConstraint("flow_id", "id", name="uq_flow_steps_flow_id_id"),
        UniqueConstraint("id", "tenant_id", name="uq_flow_steps_id_tenant_id"),
        CheckConstraint("input_source IN ('flow_input','previous_step','all_previous_steps','http_get','http_post')", name="ck_flow_steps_input_source"),
        CheckConstraint("input_type IN ('text','json','image','audio','document','file','any')", name="ck_flow_steps_input_type"),
        CheckConstraint(
            "output_mode IN ('pass_through','http_post','transcribe_only')",
            name="ck_flow_steps_output_mode",
        ),
        CheckConstraint("output_type IN ('text','json','pdf','docx')", name="ck_flow_steps_output_type"),
        CheckConstraint("mcp_policy IN ('inherit','restricted')", name="ck_flow_steps_mcp_policy"),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_steps_flow_tenant",
        ),
    )


class FlowStepMCPTools(BaseCrossReference):
    flow_step_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="CASCADE"),
        primary_key=True,
    )
    mcp_server_tool_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServerTools.id, ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_step_id", "tenant_id"],
            ["flow_steps.id", "flow_steps.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_mcp_tools_step_tenant",
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
        CheckConstraint("parent_step_id <> child_step_id", name="ck_flow_step_dependencies_no_self_ref"),
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


class FlowRuns(BasePublic):
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_version: Mapped[int] = mapped_column(nullable=False)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        index=True,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_flow_runs_status"),
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
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    effective_prompt: Mapped[Optional[str]] = mapped_column(nullable=True)
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    model_parameters_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    num_tokens_input: Mapped[Optional[int]] = mapped_column(nullable=True)
    num_tokens_output: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
    )
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    flow_step_execution_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    tool_calls_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','running','completed','failed','cancelled')", name="ck_flow_step_results_status"),
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
        UniqueConstraint("flow_run_id", "step_id", name="uq_flow_step_results_run_step"),
        Index("ix_flow_step_results_run_flow_step", "flow_run_id", "flow_id", "step_id"),
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
    celery_task_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('started','retried','failed','completed','cancelled')", name="ck_flow_step_attempts_status"),
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
    )


class ModuleRegistry(BasePublic):
    name: Mapped[str] = mapped_column(nullable=False)
    module_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    internal_url: Mapped[str] = mapped_column(nullable=False)
    health_endpoint: Mapped[str] = mapped_column(nullable=False, server_default="/health")
    last_health_check_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
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
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("last_health_status IN ('healthy','unhealthy','unknown')", name="ck_module_registry_last_health_status"),
        CheckConstraint("compat_status IN ('compatible','incompatible','unknown')", name="ck_module_registry_compat_status"),
    )
