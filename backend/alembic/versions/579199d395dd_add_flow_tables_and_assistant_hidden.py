"""flow foundation migration

Revision ID: 579199d395dd
Revises: 202604101000
Create Date: 2026-03-01 11:15:44.279045
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic
revision = "579199d395dd"
down_revision = "202604101000"
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
    op.add_column(
        "tenants",
        sa.Column(
            "flow_settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
        sa.Column(
            "draft_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Monotonic counter for optimistic locking on draft mutations.",
        ),
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
            "output_mode IN ('pass_through','http_post','transcribe_only','template_fill')",
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
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_type",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
        sa.Column("principal_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("principal_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("dispatch_pending_since", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "dispatch_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "dispatch_last_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("dispatch_last_error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "dispatch_next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dispatch_exhausted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("output_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "principal_type IN ('user','service_key')",
            name="ck_flow_runs_principal_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_flow_runs_status",
        ),
        sa.CheckConstraint(
            "dispatch_attempt_count >= 0",
            name="ck_flow_runs_dispatch_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "dispatch_last_error IS NULL "
            "OR jsonb_typeof(dispatch_last_error) = 'object'",
            name="ck_flow_runs_dispatch_last_error_object",
        ),
        sa.CheckConstraint(
            """
            (
                principal_type = 'user'
                AND principal_user_id IS NOT NULL
                AND principal_api_key_id IS NULL
            )
            OR (
                principal_type = 'service_key'
                AND principal_user_id IS NULL
                AND principal_api_key_id IS NOT NULL
            )
            """,
            name="ck_flow_runs_principal_identity",
        ),
        sa.ForeignKeyConstraint(
            ["principal_user_id"],
            ["users.id"],
            name="fk_flow_runs_principal_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["principal_api_key_id"],
            ["api_keys_v2.id"],
            name="fk_flow_runs_principal_api_key_id",
            ondelete="RESTRICT",
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
    op.create_index(
        "ix_flow_runs_queued_dispatch_due",
        "flow_runs",
        ["tenant_id", "dispatch_next_attempt_at", "id"],
        unique=False,
        postgresql_where=sa.text(
            "status = 'queued' "
            "AND dispatch_next_attempt_at IS NOT NULL "
            "AND dispatch_exhausted_at IS NULL"
        ),
    )
    op.create_index(
        "uq_flow_runs_idempotency_user_key",
        "flow_runs",
        ["tenant_id", "flow_id", "principal_user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("principal_type = 'user' AND idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_flow_runs_idempotency_service_key",
        "flow_runs",
        ["tenant_id", "flow_id", "principal_api_key_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "principal_type = 'service_key' AND idempotency_key IS NOT NULL"
        ),
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
            "status IN ('started','failed','completed','cancelled')",
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

    op.add_column(
        "assistants",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "assistants",
        sa.Column("managing_flow_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        "flows",
        ["managing_flow_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_assistants_origin",
        "assistants",
        "origin IN ('user','flow_managed')",
    )
    op.create_check_constraint(
        "ck_assistants_origin_flow_owner",
        "assistants",
        "(origin = 'user' AND managing_flow_id IS NULL) OR "
        "(origin = 'flow_managed' AND managing_flow_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_assistants_flow_managed_hidden",
        "assistants",
        "origin <> 'flow_managed' OR hidden = true",
    )
    op.create_index(
        "ix_assistants_origin_managing_flow",
        "assistants",
        ["origin", "managing_flow_id"],
        unique=False,
    )

    conn = op.get_bind()
    conflicting_rows = conn.execute(
        sa.text(
            """
            SELECT assistant_id
            FROM flow_steps
            GROUP BY assistant_id
            HAVING COUNT(DISTINCT flow_id) > 1
            """
        )
    ).fetchall()
    if conflicting_rows:
        conflicting_ids = ", ".join(str(row[0]) for row in conflicting_rows[:10])
        raise RuntimeError(
            "Flow assistant ownership backfill conflict: assistants linked to multiple flows. "
            f"Example assistant IDs: {conflicting_ids}"
        )

    conn.execute(
        sa.text(
            """
            UPDATE assistants AS a
            SET origin = 'flow_managed',
                managing_flow_id = flow_refs.flow_id,
                hidden = true
            FROM (
                SELECT DISTINCT ON (assistant_id) assistant_id, flow_id
                FROM flow_steps
                ORDER BY assistant_id, flow_id
            ) AS flow_refs
            WHERE a.id = flow_refs.assistant_id
            """
        )
    )

    op.create_table(
        "flow_template_assets",
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("mimetype", sa.String(), nullable=True),
        sa.Column(
            "placeholders",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ready','needs_action','read_only','unavailable')",
            name="ck_flow_template_assets_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_template_assets_flow_tenant",
        ),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_flow_template_assets_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_flow_template_assets_flow_id"),
        "flow_template_assets",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_space_id"),
        "flow_template_assets",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_tenant_id"),
        "flow_template_assets",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_file_id"),
        "flow_template_assets",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_template_assets_flow_active",
        "flow_template_assets",
        ["flow_id", "updated_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_flow_template_assets_flow_active", table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_file_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_tenant_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_space_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_flow_id"), table_name="flow_template_assets")
    op.drop_table("flow_template_assets")

    op.drop_index("ix_assistants_origin_managing_flow", table_name="assistants")
    op.drop_constraint("ck_assistants_flow_managed_hidden", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin_flow_owner", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin", "assistants", type_="check")
    op.drop_constraint(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        type_="foreignkey",
    )
    op.drop_column("assistants", "managing_flow_id")
    op.drop_column("assistants", "origin")

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

    op.drop_index("ix_flow_runs_queued_dispatch_due", table_name="flow_runs")
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

    op.drop_index("ix_flow_steps_tenant_id", table_name="flow_steps")
    op.drop_index("ix_flow_steps_flow_id", table_name="flow_steps")
    op.drop_table("flow_steps")

    op.drop_index("uq_flows_space_id_name_active", table_name="flows")
    op.drop_index("ix_flows_space_deleted", table_name="flows")
    op.drop_table("flows")

    op.drop_column("tenants", "flow_settings")
    op.drop_column("assistants", "hidden")
