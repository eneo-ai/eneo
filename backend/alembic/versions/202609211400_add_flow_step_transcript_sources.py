"""add flow step transcript sources

Revision ID: 202609211400
Revises: 202609211300
Create Date: 2026-09-21 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609211400"
down_revision: str | None = "202609211300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "flow_step_transcript_sources",
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
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("segments_json", JSONB(none_as_null=True), nullable=True),
        sa.Column("detail_json", JSONB(none_as_null=True), nullable=True),
        sa.Column("segments_bytes", sa.Integer(), nullable=False),
        sa.Column("detail_bytes", sa.Integer(), nullable=False),
        sa.Column("words_bytes", sa.Integer(), nullable=False),
        sa.Column("segments_count", sa.Integer(), nullable=False),
        sa.Column("words_count", sa.Integer(), nullable=False),
        sa.Column("segments_omitted_reason", sa.SmallInteger(), nullable=True),
        sa.Column("detail_omitted_reason", sa.SmallInteger(), nullable=True),
        sa.Column("words_omitted_reason", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "attempt_no >= 1 AND segments_bytes >= 0 AND detail_bytes >= 0 AND words_bytes >= 0 AND segments_count >= 0 AND words_count >= 0",
            name="ck_transcript_sources_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_step_transcript_sources_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            ondelete="CASCADE",
            name="fk_step_transcript_sources_flow",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_transcript_sources_run_tenant",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_transcript_sources_attempt",
        ),
    )
    op.create_index(
        "ix_flow_step_transcript_sources_tenant_id",
        "flow_step_transcript_sources",
        ["tenant_id"],
    )
    op.create_index(
        "ix_flow_step_transcript_sources_flow_id",
        "flow_step_transcript_sources",
        ["flow_id"],
    )
    op.create_index(
        "ix_flow_step_transcript_sources_flow_run_id",
        "flow_step_transcript_sources",
        ["flow_run_id"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE flow_step_transcript_sources IN ACCESS EXCLUSIVE MODE")
    retained = (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM flow_step_transcript_sources)"))
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Refusing to downgrade 202609211400: authoritative transcript sources "
            "are still referenced by step attempts."
        )
    op.drop_table("flow_step_transcript_sources")
