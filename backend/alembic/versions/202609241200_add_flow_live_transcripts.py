"""Store clean live transcription sessions.

Revision ID: 202609241200
Revises: 202609231200
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609241200"
down_revision: str | None = "202609231200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "flow_live_transcripts",
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
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=False),
        sa.Column("flow_version", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("recording_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segments", JSONB(none_as_null=True), nullable=True),
        sa.Column("received_audio_seconds", sa.Double(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("bound_file_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_live_transcripts_flow_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["bound_file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_live_transcripts_file_tenant",
        ),
        sa.CheckConstraint(
            "received_audio_seconds >= 0 AND flow_version >= 1",
            name="ck_flow_live_transcripts_bounds",
        ),
    )
    for column in ("tenant_id", "user_id", "flow_id", "bound_file_id"):
        op.create_index(
            f"ix_flow_live_transcripts_{column}", "flow_live_transcripts", [column]
        )
    op.create_index(
        "ix_flow_live_transcripts_unbound_expiry",
        "flow_live_transcripts",
        ["expires_at", "id"],
        postgresql_where=sa.text("bound_file_id IS NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE flow_live_transcripts IN ACCESS EXCLUSIVE MODE")
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM flow_live_transcripts)"))
        .scalar_one()
    ):
        raise RuntimeError(
            "Refusing to discard stored live transcripts during downgrade."
        )
    op.drop_table("flow_live_transcripts")
