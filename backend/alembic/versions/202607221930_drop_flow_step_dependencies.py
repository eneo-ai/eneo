"""Drop the unused Flow step dependencies table.

Revision ID: 202607221930_drop_step_deps
Revises: 202607151200_retention_barrier
Create Date: 2026-07-22 19:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202607221930_drop_step_deps"
down_revision = "202607151200_retention_barrier"
branch_labels = None
depends_on = None

_TABLE_NAME = "flow_step_dependencies"


def upgrade() -> None:
    op.execute(f"LOCK TABLE {_TABLE_NAME} IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {_TABLE_NAME}) THEN
                RAISE EXCEPTION
                    'Cannot drop flow_step_dependencies while rows exist';
            END IF;
        END
        $$
        """
    )
    op.drop_table(_TABLE_NAME)


def downgrade() -> None:
    op.create_table(
        _TABLE_NAME,
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
        _TABLE_NAME,
        ["tenant_id"],
        unique=False,
    )
