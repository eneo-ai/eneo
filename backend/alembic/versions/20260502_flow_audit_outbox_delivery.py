"""Add flow audit outbox delivery state.

Revision ID: 20260502_flow_audit_delivery
Revises: 20260502_flow_step_review_policy
Create Date: 2026-05-02 21:12:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260502_flow_audit_delivery"
down_revision = "20260502_flow_step_review_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column(
            "delivery_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column(
            "next_delivery_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("dead_lettered_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("delivery_last_error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_delivery_attempts",
        "flow_run_audit_outbox",
        "delivery_attempts >= 0",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_delivery_status",
        "flow_run_audit_outbox",
        "delivery_status IN ('pending','delivered','dead_lettered')",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_delivery_timestamps",
        "flow_run_audit_outbox",
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
    )
    op.create_index(
        "ix_flow_run_audit_outbox_pending_delivery",
        "flow_run_audit_outbox",
        ["next_delivery_at", "created_at"],
        postgresql_where=sa.text("delivery_status = 'pending'"),
    )
    op.create_index(
        "ix_flow_run_audit_outbox_dead_lettered",
        "flow_run_audit_outbox",
        ["dead_lettered_at"],
        postgresql_where=sa.text("delivery_status = 'dead_lettered'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_flow_run_audit_outbox_dead_lettered",
        table_name="flow_run_audit_outbox",
    )
    op.drop_index(
        "ix_flow_run_audit_outbox_pending_delivery",
        table_name="flow_run_audit_outbox",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_delivery_timestamps",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_delivery_status",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_delivery_attempts",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_column("flow_run_audit_outbox", "delivery_last_error")
    op.drop_column("flow_run_audit_outbox", "dead_lettered_at")
    op.drop_column("flow_run_audit_outbox", "delivered_at")
    op.drop_column("flow_run_audit_outbox", "next_delivery_at")
    op.drop_column("flow_run_audit_outbox", "delivery_attempts")
    op.drop_column("flow_run_audit_outbox", "delivery_status")
