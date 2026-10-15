"""Keep why the last connection check failed, and whether the service times words.

A failed check keeps a closed reason (unreachable, timeout, http_status with the
status, malformed, credentials) for every administrator, and every check keeps
whether the service lists the timestamp task. Existing checks keep neither until
they are run again.

Revision ID: 202610141005
Revises: 202610111900
"""

import sqlalchemy as sa

from alembic import op

revision = "202610141005"
down_revision = "202610111900"
branch_labels = None
depends_on = None

_TABLE = "transcription_service_connections"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("last_check_times_words", sa.Boolean(), nullable=True))
    op.add_column(_TABLE, sa.Column("last_check_reason", sa.String(32), nullable=True))
    op.add_column(
        _TABLE, sa.Column("last_check_status_code", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "last_check_status_code")
    op.drop_column(_TABLE, "last_check_reason")
    op.drop_column(_TABLE, "last_check_times_words")
