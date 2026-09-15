"""add review change history

Revision ID: 202609151000
Revises: 202609131200
Create Date: 2026-09-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609151000"
down_revision: str | None = "202609131200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_transcript_corrections_id_tenant",
        "flow_transcript_corrections",
        ["id", "tenant_id"],
    )
    op.create_table(
        "flow_transcript_correction_revisions",
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
        sa.Column("correction_set_id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=False),
        sa.Column("flow_run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("occurrences_json", JSONB(), nullable=False),
        sa.Column("speaker_edits_json", JSONB(), nullable=False),
        sa.Column("segments_hash", sa.String(64), nullable=False),
        sa.Column("edited_by_user_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_service_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_principal_type", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["correction_set_id"],
            ["flow_transcript_corrections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["correction_set_id", "tenant_id"],
            ["flow_transcript_corrections.id", "flow_transcript_corrections.tenant_id"],
            ondelete="CASCADE",
            name="fk_correction_revisions_set_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_service_id"], ["service_principals.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "correction_set_id", "revision", name="uq_correction_revisions_set_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_correction_revisions_revision"),
        sa.CheckConstraint(
            "(edited_by_principal_type = 'user' AND edited_by_user_id IS NOT NULL "
            "AND edited_by_service_id IS NULL) OR "
            "(edited_by_principal_type = 'service_key' AND edited_by_user_id IS NULL "
            "AND edited_by_service_id IS NOT NULL)",
            name="ck_correction_revisions_editor_principal",
        ),
    )
    op.create_index(
        "ix_flow_transcript_correction_revisions_flow_run_id",
        "flow_transcript_correction_revisions",
        ["flow_run_id"],
    )
    op.execute(
        sa.text("""
        INSERT INTO flow_transcript_correction_revisions (
            tenant_id, correction_set_id, flow_id, flow_run_id, step_id, revision,
            occurrences_json, speaker_edits_json, segments_hash,
            edited_by_user_id, edited_by_service_id, edited_by_principal_type,
            created_at, updated_at
        )
        SELECT tenant_id, id, flow_id, flow_run_id, step_id, revision,
               occurrences_json, speaker_edits_json, segments_hash,
               edited_by_user_id, edited_by_service_id, edited_by_principal_type,
               updated_at, updated_at
        FROM flow_transcript_corrections
    """)
    )
    op.create_unique_constraint(
        "uq_review_checkpoints_id_tenant",
        "flow_run_review_checkpoints",
        ["id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_review_checkpoints_id_run",
        "flow_run_review_checkpoints",
        ["id", "flow_run_id"],
    )
    op.create_table(
        "flow_run_review_checkpoint_edits",
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
        sa.Column("checkpoint_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cause", sa.String(32), nullable=False),
        sa.Column("corrections_revision_id", sa.UUID(), nullable=True),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.Column("payload_sha256_before", sa.String(64), nullable=False),
        sa.Column("payload_sha256_after", sa.String(64), nullable=False),
        sa.Column("edited_by_user_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_service_id", sa.UUID(), nullable=True),
        sa.Column("edited_by_principal_type", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"], ["flow_run_review_checkpoints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["corrections_revision_id"],
            ["flow_transcript_correction_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_service_id"], ["service_principals.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "checkpoint_id", "revision", name="uq_checkpoint_edits_checkpoint_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_checkpoint_edits_revision"),
        sa.CheckConstraint(
            "cause IN ('reviewer_edit', 'corrections_folded')",
            name="ck_checkpoint_edits_cause",
        ),
        sa.CheckConstraint(
            "(corrections_revision_id IS NOT NULL) = (cause = 'corrections_folded')",
            name="ck_checkpoint_edits_correction_reference",
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_id", "tenant_id"],
            ["flow_run_review_checkpoints.id", "flow_run_review_checkpoints.tenant_id"],
            ondelete="CASCADE",
            name="fk_checkpoint_edits_checkpoint_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_id", "flow_run_id"],
            [
                "flow_run_review_checkpoints.id",
                "flow_run_review_checkpoints.flow_run_id",
            ],
            ondelete="CASCADE",
            name="fk_checkpoint_edits_checkpoint_run",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_checkpoint_edits_run_tenant",
        ),
        sa.CheckConstraint(
            "(edited_by_principal_type = 'user' AND edited_by_user_id IS NOT NULL "
            "AND edited_by_service_id IS NULL) OR "
            "(edited_by_principal_type = 'service_key' AND edited_by_user_id IS NULL "
            "AND edited_by_service_id IS NOT NULL)",
            name="ck_checkpoint_edits_editor_principal",
        ),
    )
    op.create_index(
        "ix_flow_run_review_checkpoint_edits_flow_run_id",
        "flow_run_review_checkpoint_edits",
        ["flow_run_id"],
    )
    op.create_index(
        "ix_flow_run_review_checkpoint_edits_corrections_revision_id",
        "flow_run_review_checkpoint_edits",
        ["corrections_revision_id"],
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("payload_sha256_before", sa.String(64), nullable=True),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("payload_sha256_after", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_run_audit_outbox", "payload_sha256_after")
    op.drop_column("flow_run_audit_outbox", "payload_sha256_before")
    op.drop_table("flow_run_review_checkpoint_edits")
    op.drop_constraint(
        "uq_review_checkpoints_id_run", "flow_run_review_checkpoints", type_="unique"
    )
    op.drop_constraint(
        "uq_review_checkpoints_id_tenant", "flow_run_review_checkpoints", type_="unique"
    )
    op.drop_table("flow_transcript_correction_revisions")
    op.drop_constraint(
        "uq_transcript_corrections_id_tenant",
        "flow_transcript_corrections",
        type_="unique",
    )
