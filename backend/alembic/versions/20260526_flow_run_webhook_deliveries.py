"""add flow run webhook deliveries outbox

Revision ID: 20260526_flow_webhook_deliveries
Revises: 20260526_flow_step_identity
Create Date: 2026-05-26 11:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260526_flow_webhook_deliveries"
down_revision = "20260526_flow_step_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_run_webhook_deliveries",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "flow_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "delivery_status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "next_delivery_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivery_last_error", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_flow_run_webhook_deliveries_attempt_no",
        ),
        sa.CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_flow_run_webhook_deliveries_delivery_attempts",
        ),
        sa.CheckConstraint(
            "idempotency_key <> ''",
            name="ck_flow_run_webhook_deliveries_idempotency_key",
        ),
        sa.CheckConstraint(
            "payload_ref <> ''",
            name="ck_flow_run_webhook_deliveries_payload_ref",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending','delivered','dead_lettered')",
            name="ck_flow_run_webhook_deliveries_status",
        ),
        sa.CheckConstraint(
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
            name="ck_flow_run_webhook_deliveries_delivery_timestamps",
        ),
        sa.CheckConstraint(
            "("
            "(claim_token IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL) "
            "OR "
            "(delivery_status = 'pending' "
            "AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL)"
            ")",
            name="ck_flow_run_webhook_deliveries_claim_shape",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_webhook_deliveries_run_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_webhook_deliveries_run_flow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_run_webhook_deliveries_attempt",
        ),
    )

    with op.get_context().autocommit_block():
        op.create_index(
            "ix_flow_run_webhook_deliveries_tenant_id",
            "flow_run_webhook_deliveries",
            ["tenant_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_flow_id",
            "flow_run_webhook_deliveries",
            ["flow_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_flow_run_id",
            "flow_run_webhook_deliveries",
            ["flow_run_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_tenant_created",
            "flow_run_webhook_deliveries",
            ["tenant_id", "created_at"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_pending_delivery",
            "flow_run_webhook_deliveries",
            ["next_delivery_at", "created_at"],
            postgresql_where=sa.text("delivery_status = 'pending'"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_pending_run_tenant",
            "flow_run_webhook_deliveries",
            ["flow_run_id", "tenant_id"],
            postgresql_where=sa.text("delivery_status = 'pending'"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_flow_run_webhook_deliveries_dead_lettered",
            "flow_run_webhook_deliveries",
            ["dead_lettered_at"],
            postgresql_where=sa.text("delivery_status = 'dead_lettered'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_flow_run_webhook_deliveries_dead_lettered",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_pending_run_tenant",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_pending_delivery",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_tenant_created",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_flow_run_id",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_flow_id",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_flow_run_webhook_deliveries_tenant_id",
            table_name="flow_run_webhook_deliveries",
            postgresql_concurrently=True,
        )

    op.drop_table("flow_run_webhook_deliveries")
