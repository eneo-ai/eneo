"""Keep content-free source release evidence with its run, without a file FK."""

import sqlalchemy as sa

from alembic import op

revision = "202610061800"
down_revision = "202610061700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "flow_run_released_inputs",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "step_id", "file_id"),
        sa.ForeignKeyConstraint(["run_id"], ["flow_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "reason IN ('transcription_audio_after_use')",
            name="ck_flow_run_released_inputs_reason",
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("flow_run_released_inputs")
