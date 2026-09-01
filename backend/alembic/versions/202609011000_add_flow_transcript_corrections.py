"""add flow transcript corrections

Revision ID: 202609011000
Revises: 202608251330
Create Date: 2026-09-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609011000"
down_revision: str | None = "202608301535"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flow_transcript_corrections",
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
        sa.Column("occurrences_json", JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("segments_hash", sa.String(length=64), nullable=False),
        sa.Column("edited_by_user_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_service_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_principal_type", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_transcript_corrections_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            ondelete="CASCADE",
            name="fk_transcript_corrections_flow",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_transcript_corrections_edited_by_user",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_service_id"],
            ["service_principals.id"],
            ondelete="RESTRICT",
            name="fk_transcript_corrections_edited_by_service",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_transcript_corrections_run_tenant",
        ),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            name="uq_flow_transcript_corrections_run_step",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_flow_transcript_corrections_revision",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_flow_transcript_corrections_schema_version",
        ),
        sa.CheckConstraint(
            "("
            "edited_by_principal_type = 'user' "
            "AND edited_by_user_id IS NOT NULL "
            "AND edited_by_service_id IS NULL"
            ") OR ("
            "edited_by_principal_type = 'service_key' "
            "AND edited_by_user_id IS NULL "
            "AND edited_by_service_id IS NOT NULL"
            ")",
            name="ck_flow_transcript_corrections_editor_principal",
        ),
    )
    op.create_index(
        "ix_flow_transcript_corrections_tenant_id",
        "flow_transcript_corrections",
        ["tenant_id"],
    )
    op.create_index(
        "ix_flow_transcript_corrections_flow_id",
        "flow_transcript_corrections",
        ["flow_id"],
    )
    op.create_index(
        "ix_flow_transcript_corrections_flow_run_id",
        "flow_transcript_corrections",
        ["flow_run_id"],
    )


def downgrade() -> None:
    op.drop_table("flow_transcript_corrections")
