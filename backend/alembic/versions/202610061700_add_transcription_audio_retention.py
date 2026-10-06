"""Add opt-in source-audio retention flags without rewriting existing rows."""

import sqlalchemy as sa

from alembic import op

revision = "202610061700"
down_revision = "202610061600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in ("tenants", "spaces", "flows"):
        op.add_column(
            table,
            sa.Column(
                "delete_transcription_audio_after_use", sa.Boolean(), nullable=True
            ),
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in ("flows", "spaces", "tenants"):
        op.drop_column(table, "delete_transcription_audio_after_use")
