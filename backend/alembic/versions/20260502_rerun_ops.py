"""add flow run rerun operations

Revision ID: 20260502_rerun_ops
Revises: 20260430_flow_step_file_mappings
Create Date: 2026-05-02 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260502_rerun_ops"
down_revision = "20260430_flow_step_file_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment=(
                "Monotonic lifecycle compare-and-swap token; its value on entry "
                "to queued identifies the dispatch epoch. updated_at is display "
                "metadata."
            ),
        ),
    )
    op.add_column(
        "flow_step_results",
        sa.Column(
            "current_attempt_no", sa.Integer(), nullable=True, server_default="1"
        ),
    )

    op.create_table(
        "flow_run_rerun_operations",
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
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rerun_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rerun_step_order", sa.Integer(), nullable=False),
        sa.Column("root_attempt_no", sa.Integer(), nullable=False),
        sa.Column("root_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("expected_run_revision", sa.Integer(), nullable=False),
        sa.Column("accepted_run_revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("root_step_input_override_requested", sa.Boolean(), nullable=False),
        sa.Column(
            "requested_by_principal_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_flow_run_rerun_operations_status",
        ),
        sa.CheckConstraint(
            "requested_by_principal_type = 'user'",
            name="ck_flow_run_rerun_operations_user_principal",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_rerun_operations_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name=op.f("fk_flow_run_rerun_operations_run_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name=op.f("fk_flow_run_rerun_operations_run_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_rerun_operations_requested_by_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["root_attempt_id"],
            ["flow_step_attempts.id"],
            name=op.f("fk_rerun_operations_root_attempt"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_rerun_operations_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_run_rerun_operations")),
        sa.UniqueConstraint(
            "tenant_id",
            "flow_run_id",
            "request_fingerprint",
            name="uq_flow_run_rerun_operations_request_fingerprint",
        ),
    )
    op.create_index(
        "ix_flow_run_rerun_operations_flow_id",
        "flow_run_rerun_operations",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_operations_flow_run_id",
        "flow_run_rerun_operations",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_operations_run_status",
        "flow_run_rerun_operations",
        ["flow_run_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_operations_run_step",
        "flow_run_rerun_operations",
        ["flow_run_id", "rerun_step_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_operations_tenant_created_at",
        "flow_run_rerun_operations",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_operations_tenant_id",
        "flow_run_rerun_operations",
        ["tenant_id"],
        unique=False,
    )

    op.add_column(
        "flow_step_attempts",
        sa.Column("rerun_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column(
            "predecessor_attempt_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column(
            "superseded_by_attempt_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("input_payload_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("output_payload_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("flow_step_execution_hash", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_step_attempts_rerun_operation"),
        "flow_step_attempts",
        "flow_run_rerun_operations",
        ["rerun_operation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_step_attempts_predecessor"),
        "flow_step_attempts",
        "flow_step_attempts",
        ["predecessor_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_step_attempts_superseded_by"),
        "flow_step_attempts",
        "flow_step_attempts",
        ["superseded_by_attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_flow_step_attempts_predecessor_attempt",
        "flow_step_attempts",
        ["predecessor_attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_step_attempts_rerun_operation",
        "flow_step_attempts",
        ["rerun_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_step_attempts_superseded_by_attempt",
        "flow_step_attempts",
        ["superseded_by_attempt_id"],
        unique=False,
    )

    op.create_table(
        "flow_run_rerun_invalidated_steps",
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
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("invalidation_order", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "dependency_sources_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("prior_step_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prior_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("new_attempt_no", sa.Integer(), nullable=True),
        sa.Column("new_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('root','downstream')",
            name="ck_flow_run_rerun_invalidated_steps_role",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_rerun_invalidated_steps_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name=op.f("fk_flow_run_rerun_invalidated_steps_run_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name=op.f("fk_flow_run_rerun_invalidated_steps_run_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["new_attempt_id"],
            ["flow_step_attempts.id"],
            name=op.f("fk_rerun_invalidated_steps_new_attempt"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["flow_run_rerun_operations.id"],
            name=op.f("fk_rerun_invalidated_steps_operation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prior_attempt_id"],
            ["flow_step_attempts.id"],
            name=op.f("fk_rerun_invalidated_steps_prior_attempt"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prior_step_result_id"],
            ["flow_step_results.id"],
            name=op.f("fk_rerun_invalidated_steps_prior_result"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_rerun_invalidated_steps_tenant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_run_rerun_invalidated_steps")),
        sa.UniqueConstraint(
            "operation_id",
            "invalidation_order",
            name="uq_flow_run_rerun_invalidated_steps_operation_order",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "step_id",
            name="uq_flow_run_rerun_invalidated_steps_operation_step",
        ),
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_flow_id",
        "flow_run_rerun_invalidated_steps",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_flow_run_id",
        "flow_run_rerun_invalidated_steps",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_new_attempt",
        "flow_run_rerun_invalidated_steps",
        ["new_attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_operation_id",
        "flow_run_rerun_invalidated_steps",
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_prior_attempt",
        "flow_run_rerun_invalidated_steps",
        ["prior_attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_run_step",
        "flow_run_rerun_invalidated_steps",
        ["flow_run_id", "step_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_rerun_invalidated_steps_tenant_id",
        "flow_run_rerun_invalidated_steps",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_tenant_id",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_run_step",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_prior_attempt",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_operation_id",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_new_attempt",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_flow_run_id",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_index(
        "ix_flow_run_rerun_invalidated_steps_flow_id",
        table_name="flow_run_rerun_invalidated_steps",
    )
    op.drop_table("flow_run_rerun_invalidated_steps")

    op.drop_index(
        "ix_flow_step_attempts_superseded_by_attempt",
        table_name="flow_step_attempts",
    )
    op.drop_index(
        "ix_flow_step_attempts_rerun_operation",
        table_name="flow_step_attempts",
    )
    op.drop_index(
        "ix_flow_step_attempts_predecessor_attempt",
        table_name="flow_step_attempts",
    )
    op.drop_constraint(
        op.f("fk_step_attempts_superseded_by"),
        "flow_step_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_step_attempts_predecessor"),
        "flow_step_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_step_attempts_rerun_operation"),
        "flow_step_attempts",
        type_="foreignkey",
    )
    op.drop_column("flow_step_attempts", "flow_step_execution_hash")
    op.drop_column("flow_step_attempts", "output_payload_json")
    op.drop_column("flow_step_attempts", "input_payload_json")
    op.drop_column("flow_step_attempts", "superseded_by_attempt_id")
    op.drop_column("flow_step_attempts", "predecessor_attempt_id")
    op.drop_column("flow_step_attempts", "rerun_operation_id")

    op.drop_index(
        "ix_flow_run_rerun_operations_tenant_id",
        table_name="flow_run_rerun_operations",
    )
    op.drop_index(
        "ix_flow_run_rerun_operations_tenant_created_at",
        table_name="flow_run_rerun_operations",
    )
    op.drop_index(
        "ix_flow_run_rerun_operations_run_step",
        table_name="flow_run_rerun_operations",
    )
    op.drop_index(
        "ix_flow_run_rerun_operations_run_status",
        table_name="flow_run_rerun_operations",
    )
    op.drop_index(
        "ix_flow_run_rerun_operations_flow_run_id",
        table_name="flow_run_rerun_operations",
    )
    op.drop_index(
        "ix_flow_run_rerun_operations_flow_id",
        table_name="flow_run_rerun_operations",
    )
    op.drop_table("flow_run_rerun_operations")

    op.drop_column("flow_step_results", "current_attempt_no")
    op.drop_column("flow_runs", "revision")
