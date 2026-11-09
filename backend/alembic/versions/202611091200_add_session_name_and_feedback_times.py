"""Record when a conversation's name and feedback text were written.

Revision ID: 202611091200
Revises: 202611091110
Conversation history removes each on its own time. An existing conversation gets
its creation time: never later than its first question, so nothing written before
the upgrade is kept longer than its period allows. The update rewrites every row
of `sessions` under the lock the new columns take. Downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611091200"
down_revision: str = "202611091110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("name_set_at", "feedback_set_at")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "sessions", sa.Column(column, sa.TIMESTAMP(timezone=True), nullable=True)
        )
    op.execute(
        "UPDATE sessions SET name_set_at = created_at, feedback_set_at = created_at"
    )
    for column in _COLUMNS:
        op.alter_column(
            "sessions", column, nullable=False, server_default=sa.text("now()")
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("sessions", column)
