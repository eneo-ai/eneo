"""add flow run step file mappings

Revision ID: 20260430_flow_step_file_mappings
Revises: 20260430_flow_run_audit_outbox
Create Date: 2026-04-30 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260430_flow_step_file_mappings"
down_revision = "20260430_flow_run_audit_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_run_step_input_files",
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
        sa.Column("flow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column(
            "attempt_no",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_flow_run_step_input_files_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_flow_run_step_input_files_flow_id_flows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name=op.f("fk_flow_run_step_input_files_run_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name=op.f("fk_flow_run_step_input_files_run_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_run_step_input_files_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_run_step_input_files")),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_input_files_run_step_attempt_file",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_input_files_run_step_attempt_ordinal",
        ),
    )
    op.create_index(
        "ix_flow_run_step_input_files_file_id",
        "flow_run_step_input_files",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_flow_id",
        "flow_run_step_input_files",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_flow_run_id",
        "flow_run_step_input_files",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_flow_step",
        "flow_run_step_input_files",
        ["flow_id", "step_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_run_step_attempt",
        "flow_run_step_input_files",
        ["flow_run_id", "step_id", "attempt_no"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_tenant_file",
        "flow_run_step_input_files",
        ["tenant_id", "file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_input_files_tenant_id",
        "flow_run_step_input_files",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "flow_run_step_result_files",
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
        sa.Column("flow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "source IN ('generated_output','declared_artifact')",
            name="ck_flow_run_step_result_files_source",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_flow_run_step_result_files_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_flow_run_step_result_files_flow_id_flows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name=op.f("fk_flow_run_step_result_files_run_flow"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name=op.f("fk_flow_run_step_result_files_run_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_result_id"],
            ["flow_step_results.id"],
            name=op.f(
                "fk_flow_run_step_result_files_step_result_id_flow_step_results"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_run_step_result_files_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_run_step_result_files")),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_result_files_run_step_attempt_file",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_result_files_run_step_attempt_ordinal",
        ),
    )
    op.create_index(
        "ix_flow_run_step_result_files_file_id",
        "flow_run_step_result_files",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_flow_id",
        "flow_run_step_result_files",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_flow_run_id",
        "flow_run_step_result_files",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_run_step_attempt",
        "flow_run_step_result_files",
        ["flow_run_id", "step_id", "attempt_no"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_step_result",
        "flow_run_step_result_files",
        ["step_result_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_tenant_file",
        "flow_run_step_result_files",
        ["tenant_id", "file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_step_result_files_tenant_id",
        "flow_run_step_result_files",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_flow_run_step_result_files_tenant_id",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_tenant_file",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_step_result",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_run_step_attempt",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_flow_run_id",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_flow_id",
        table_name="flow_run_step_result_files",
    )
    op.drop_index(
        "ix_flow_run_step_result_files_file_id",
        table_name="flow_run_step_result_files",
    )
    op.drop_table("flow_run_step_result_files")

    op.drop_index(
        "ix_flow_run_step_input_files_tenant_id",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_tenant_file",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_run_step_attempt",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_flow_step",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_flow_run_id",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_flow_id",
        table_name="flow_run_step_input_files",
    )
    op.drop_index(
        "ix_flow_run_step_input_files_file_id",
        table_name="flow_run_step_input_files",
    )
    op.drop_table("flow_run_step_input_files")
