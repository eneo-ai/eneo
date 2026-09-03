"""add flow step transcript words

Revision ID: 202609031000
Revises: 202609011400
Create Date: 2026-09-03 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609031000"
down_revision: str | None = "202609011400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flow_step_transcript_words",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=False),
        sa.Column("flow_run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("segments_hash", sa.String(length=64), nullable=False),
        sa.Column("alignment", sa.String(length=32), nullable=True),
        sa.Column("words_json", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_step_transcript_words_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            ondelete="CASCADE",
            name="fk_step_transcript_words_flow",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_transcript_words_run_tenant",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            name="uq_flow_step_transcript_words_run_step",
        ),
    )
    op.create_index(
        "ix_flow_step_transcript_words_tenant_id",
        "flow_step_transcript_words",
        ["tenant_id"],
    )
    op.create_index(
        "ix_flow_step_transcript_words_flow_id",
        "flow_step_transcript_words",
        ["flow_id"],
    )
    op.create_index(
        "ix_flow_step_transcript_words_flow_run_id",
        "flow_step_transcript_words",
        ["flow_run_id"],
    )


def downgrade() -> None:
    op.drop_table("flow_step_transcript_words")
