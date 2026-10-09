"""Keep the last connection check of native transcription-service connections.

The check result is shown to every administrator after a reload, instead of
living only in the browser that ran it. Existing connections start untested.

Revision ID: 202610091000
Revises: 202610090800
"""

import sqlalchemy as sa

from alembic import op

revision = "202610091000"
down_revision = "202610090800"
branch_labels = None
depends_on = None

_TABLE = "transcription_service_connections"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("last_check_outcome", sa.String(32), nullable=True))
    op.add_column(
        _TABLE, sa.Column("last_check_identifies_speakers", sa.Boolean(), nullable=True)
    )
    op.add_column(
        _TABLE, sa.Column("last_check_service_version", sa.Text(), nullable=True)
    )
    op.add_column(
        _TABLE,
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "last_checked_at")
    op.drop_column(_TABLE, "last_check_service_version")
    op.drop_column(_TABLE, "last_check_identifies_speakers")
    op.drop_column(_TABLE, "last_check_outcome")
