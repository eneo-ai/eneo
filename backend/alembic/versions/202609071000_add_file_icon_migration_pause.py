"""Keep the temporary File/Icon migration pause across worker restarts.

Revision ID: 202609071000
Revises: 202609041000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609071000"
down_revision: str | None = "202609041000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_icon_backfill_admission_state",
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("file_icon_backfill_admission_state", "paused")
