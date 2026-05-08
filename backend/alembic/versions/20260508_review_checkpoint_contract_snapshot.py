"""Snapshot review checkpoint render contract.

Revision ID: 20260508_review_checkpoint_ui
Revises: 20260506_merge_flow_session
Create Date: 2026-05-08 08:08:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260508_review_checkpoint_ui"
down_revision = "20260506_merge_flow_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("step_label", sa.Text(), nullable=True),
    )
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("review_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("output_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("output_contract_json", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_flow_run_review_checkpoints_review_mode",
        "flow_run_review_checkpoints",
        "review_mode IS NULL OR review_mode IN ('view','edit')",
    )
    op.create_check_constraint(
        "ck_flow_run_review_checkpoints_output_type",
        "flow_run_review_checkpoints",
        "output_type IS NULL OR output_type IN ('text','json','pdf','docx')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_flow_run_review_checkpoints_output_type",
        "flow_run_review_checkpoints",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_review_checkpoints_review_mode",
        "flow_run_review_checkpoints",
        type_="check",
    )
    op.drop_column("flow_run_review_checkpoints", "output_contract_json")
    op.drop_column("flow_run_review_checkpoints", "output_type")
    op.drop_column("flow_run_review_checkpoints", "review_mode")
    op.drop_column("flow_run_review_checkpoints", "step_label")
