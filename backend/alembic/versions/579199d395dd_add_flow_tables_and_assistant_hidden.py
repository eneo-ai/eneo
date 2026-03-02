"""add flow tables and assistant hidden

Revision ID: 579199d395dd
Revises: 847ef045f3c1
Create Date: 2026-03-01 11:15:44.279045
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = "579199d395dd"
down_revision = "847ef045f3c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "flows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("data_retention_days", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("id", "tenant_id", name="uq_flows_id_tenant_id"),
    )
    op.create_index(
        "ix_flows_space_deleted",
        "flows",
        ["space_id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "uq_flows_space_id_name_active",
        "flows",
        ["space_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "flow_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("user_description", sa.String(), nullable=True),
        sa.Column(
            "input_source",
            sa.String(length=64),
            nullable=False,
            server_default="flow_input",
        ),
        sa.Column(
            "input_type",
            sa.String(length=32),
            nullable=False,
            server_default="any",
        ),
        sa.Column("input_contract", postgresql.JSONB(), nullable=True),
        sa.Column(
            "output_mode",
            sa.String(length=32),
            nullable=False,
            server_default="pass_through",
        ),
        sa.Column(
            "output_type",
            sa.String(length=32),
            nullable=False,
            server_default="text",
        ),
        sa.Column("output_contract", postgresql.JSONB(), nullable=True),
        sa.Column("input_bindings", postgresql.JSONB(), nullable=True),
        sa.Column("output_classification_override", sa.Integer(), nullable=True),
        sa.Column(
            "mcp_policy",
            sa.String(length=32),
            nullable=False,
            server_default="inherit",
        ),
        sa.Column("input_config", postgresql.JSONB(), nullable=True),
        sa.Column("output_config", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "input_source IN ('flow_input','previous_step','all_previous_steps','http_get','http_post')",
            name="ck_flow_steps_input_source",
        ),
        sa.CheckConstraint(
            "input_type IN ('text','json','image','audio','document','file','any')",
            name="ck_flow_steps_input_type",
        ),
        sa.CheckConstraint(
            "output_mode IN ('pass_through','http_post')",
            name="ck_flow_steps_output_mode",
        ),
        sa.CheckConstraint(
            "output_type IN ('text','json','pdf','docx')",
            name="ck_flow_steps_output_type",
        ),
        sa.CheckConstraint(
            "mcp_policy IN ('inherit','restricted')",
            name="ck_flow_steps_mcp_policy",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_flow_steps_flow_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("flow_id", "step_order", name="uq_flow_steps_flow_step_order"),
        sa.UniqueConstraint("flow_id", "id", name="uq_flow_steps_flow_id_id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_flow_steps_id_tenant_id"),
    )
    op.create_index("ix_flow_steps_flow_id", "flow_steps", ["flow_id"], unique=False)
    op.create_index("ix_flow_steps_tenant_id", "flow_steps", ["tenant_id"], unique=False)

    op.create_table(
        "flow_step_mcp_tools",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "mcp_server_tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_server_tools.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["flow_step_id", "tenant_id"],
            ["flow_steps.id", "flow_steps.tenant_id"],
            name="fk_flow_step_mcp_tools_step_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_flow_step_mcp_tools_tenant_id",
        "flow_step_mcp_tools",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "flow_step_dependencies",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "parent_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "child_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parent_step_id <> child_step_id",
            name="ck_flow_step_dependencies_no_self_ref",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "parent_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            name="fk_flow_step_deps_parent_same_flow",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "child_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            name="fk_flow_step_deps_child_same_flow",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_flow_step_deps_flow_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_flow_step_dependencies_tenant_id",
        "flow_step_dependencies",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "flow_versions",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("definition_checksum", sa.String(), nullable=False),
        sa.Column("definition_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_flow_versions_flow_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )
    op.create_index("ix_flow_versions_tenant_id", "flow_versions", ["tenant_id"], unique=False)

    op.create_table(
        "flow_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flow_version", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("output_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_flow_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name="fk_flow_runs_flow_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "flow_version"],
            ["flow_versions.flow_id", "flow_versions.version"],
            name="fk_flow_runs_flow_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_flow_runs_id_tenant_id"),
        sa.UniqueConstraint("id", "flow_id", name="uq_flow_runs_id_flow_id"),
    )
    op.create_index("ix_flow_runs_flow_id", "flow_runs", ["flow_id"], unique=False)
    op.create_index("ix_flow_runs_tenant_id", "flow_runs", ["tenant_id"], unique=False)
    op.create_index("ix_flow_runs_status", "flow_runs", ["status"], unique=False)
    op.create_index("ix_flow_runs_flow_id_status", "flow_runs", ["flow_id", "status"], unique=False)
    op.create_index("ix_flow_runs_tenant_created_at", "flow_runs", ["tenant_id", "created_at"], unique=False)
    op.create_index(
        "ix_flow_runs_running_updated_at",
        "flow_runs",
        ["status", "updated_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "flow_step_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column(
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("effective_prompt", sa.String(), nullable=True),
        sa.Column("output_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("model_parameters_json", postgresql.JSONB(), nullable=True),
        sa.Column("num_tokens_input", sa.Integer(), nullable=True),
        sa.Column("num_tokens_output", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("flow_step_execution_hash", sa.String(), nullable=True),
        sa.Column("tool_calls_metadata", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="ck_flow_step_results_status",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name="fk_flow_step_results_run_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name="fk_flow_step_results_run_flow",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("flow_run_id", "step_id", name="uq_flow_step_results_run_step"),
    )
    op.create_index(
        "ix_flow_step_results_flow_run_id",
        "flow_step_results",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index("ix_flow_step_results_flow_id", "flow_step_results", ["flow_id"], unique=False)
    op.create_index("ix_flow_step_results_tenant_id", "flow_step_results", ["tenant_id"], unique=False)
    op.create_index(
        "ix_flow_step_results_run_flow_step",
        "flow_step_results",
        ["flow_run_id", "flow_id", "step_id"],
        unique=False,
    )

    op.create_table(
        "flow_step_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('started','retried','failed','completed','cancelled')",
            name="ck_flow_step_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name="fk_flow_step_attempts_run_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name="fk_flow_step_attempts_run_flow",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_attempts_run_step_attempt",
        ),
    )
    op.create_index(
        "ix_flow_step_attempts_flow_run_id",
        "flow_step_attempts",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index("ix_flow_step_attempts_flow_id", "flow_step_attempts", ["flow_id"], unique=False)
    op.create_index("ix_flow_step_attempts_tenant_id", "flow_step_attempts", ["tenant_id"], unique=False)
    op.create_index(
        "ix_flow_step_attempts_run_flow_step_attempt",
        "flow_step_attempts",
        ["flow_run_id", "flow_id", "step_id", "attempt_no"],
        unique=False,
    )

    op.create_table(
        "module_registry",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("internal_url", sa.String(), nullable=False),
        sa.Column("health_endpoint", sa.String(), nullable=False, server_default="/health"),
        sa.Column("last_health_check_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_health_status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("module_version", sa.String(), nullable=True),
        sa.Column("image_digest", sa.String(), nullable=True),
        sa.Column("module_api_contract", sa.String(), nullable=True),
        sa.Column("core_compat_min", sa.String(), nullable=True),
        sa.Column("core_compat_max", sa.String(), nullable=True),
        sa.Column("compat_status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("release_notes_url", sa.String(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "last_health_status IN ('healthy','unhealthy','unknown')",
            name="ck_module_registry_last_health_status",
        ),
        sa.CheckConstraint(
            "compat_status IN ('compatible','incompatible','unknown')",
            name="ck_module_registry_compat_status",
        ),
        sa.UniqueConstraint("module_id"),
    )
    op.create_index("ix_module_registry_module_id", "module_registry", ["module_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_module_registry_module_id", table_name="module_registry")
    op.drop_table("module_registry")

    op.drop_index("ix_flow_step_attempts_run_flow_step_attempt", table_name="flow_step_attempts")
    op.drop_index("ix_flow_step_attempts_tenant_id", table_name="flow_step_attempts")
    op.drop_index("ix_flow_step_attempts_flow_id", table_name="flow_step_attempts")
    op.drop_index("ix_flow_step_attempts_flow_run_id", table_name="flow_step_attempts")
    op.drop_table("flow_step_attempts")

    op.drop_index("ix_flow_step_results_run_flow_step", table_name="flow_step_results")
    op.drop_index("ix_flow_step_results_tenant_id", table_name="flow_step_results")
    op.drop_index("ix_flow_step_results_flow_id", table_name="flow_step_results")
    op.drop_index("ix_flow_step_results_flow_run_id", table_name="flow_step_results")
    op.drop_table("flow_step_results")

    op.drop_index("ix_flow_runs_running_updated_at", table_name="flow_runs")
    op.drop_index("ix_flow_runs_tenant_created_at", table_name="flow_runs")
    op.drop_index("ix_flow_runs_flow_id_status", table_name="flow_runs")
    op.drop_index("ix_flow_runs_status", table_name="flow_runs")
    op.drop_index("ix_flow_runs_tenant_id", table_name="flow_runs")
    op.drop_index("ix_flow_runs_flow_id", table_name="flow_runs")
    op.drop_table("flow_runs")

    op.drop_index("ix_flow_versions_tenant_id", table_name="flow_versions")
    op.drop_table("flow_versions")

    op.drop_index("ix_flow_step_dependencies_tenant_id", table_name="flow_step_dependencies")
    op.drop_table("flow_step_dependencies")

    op.drop_index("ix_flow_step_mcp_tools_tenant_id", table_name="flow_step_mcp_tools")
    op.drop_table("flow_step_mcp_tools")

    op.drop_index("ix_flow_steps_tenant_id", table_name="flow_steps")
    op.drop_index("ix_flow_steps_flow_id", table_name="flow_steps")
    op.drop_table("flow_steps")

    op.drop_index("uq_flows_space_id_name_active", table_name="flows")
    op.drop_index("ix_flows_space_deleted", table_name="flows")
    op.drop_table("flows")

    op.drop_column("assistants", "hidden")
