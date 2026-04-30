"""add flow run audit outbox

Revision ID: 20260430_flow_run_audit_outbox
Revises: 20260426_drop_step_mcp_tools
Create Date: 2026-04-30 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260430_flow_run_audit_outbox"
down_revision = "20260426_drop_step_mcp_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_run_audit_outbox",
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
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("target_status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.CheckConstraint(
            "source IN ("
            "'executor_completed',"
            "'executor_failed',"
            "'flow_deleted',"
            "'definition_checksum_mismatch',"
            "'invalid_flow_definition',"
            "'assistant_snapshot_drift',"
            "'step_missing',"
            "'task_timeout',"
            "'task_failure',"
            "'missing_principal',"
            "'stale_running_reconciler',"
            "'user_cancel',"
            "'dispatch_failure'"
            ")",
            name="ck_flow_run_audit_outbox_source",
        ),
        sa.CheckConstraint(
            "target_status IN ('completed','failed','cancelled')",
            name="ck_flow_run_audit_outbox_target_status",
        ),
        sa.CheckConstraint(
            "description = action || ':' || source",
            name="ck_flow_run_audit_outbox_description",
        ),
        sa.ForeignKeyConstraint(
            ["actor_api_key_id"],
            ["api_keys_v2.id"],
            name=op.f("fk_flow_run_audit_outbox_actor_api_key_id_api_keys_v2"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_flow_run_audit_outbox_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_flow_run_audit_outbox_flow_id_flows"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            name="fk_flow_run_audit_outbox_run_flow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            name="fk_flow_run_audit_outbox_run_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_run_audit_outbox_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_run_audit_outbox")),
        sa.UniqueConstraint("flow_run_id", name="uq_flow_run_audit_outbox_run"),
    )
    op.create_index(
        "ix_flow_run_audit_outbox_action",
        "flow_run_audit_outbox",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_audit_outbox_flow_id",
        "flow_run_audit_outbox",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_audit_outbox_flow_run_id",
        "flow_run_audit_outbox",
        ["flow_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_audit_outbox_tenant_created",
        "flow_run_audit_outbox",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_flow_run_audit_outbox_tenant_id",
        "flow_run_audit_outbox",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_flow_run_audit_outbox_tenant_id", table_name="flow_run_audit_outbox")
    op.drop_index(
        "ix_flow_run_audit_outbox_tenant_created",
        table_name="flow_run_audit_outbox",
    )
    op.drop_index(
        "ix_flow_run_audit_outbox_flow_run_id",
        table_name="flow_run_audit_outbox",
    )
    op.drop_index("ix_flow_run_audit_outbox_flow_id", table_name="flow_run_audit_outbox")
    op.drop_index("ix_flow_run_audit_outbox_action", table_name="flow_run_audit_outbox")
    op.drop_table("flow_run_audit_outbox")
