"""add sharepoint subscription health fields

Revision ID: 202606251200
Revises: 202606151000
Create Date: 2026-06-25 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202606251200"
down_revision: Union[str, None] = "202606151000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sharepoint_subscriptions",
        sa.Column(
            "consecutive_renewal_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "sharepoint_subscriptions",
        sa.Column("last_renewal_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sharepoint_subscriptions",
        sa.Column("last_renewal_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "sharepoint_subscriptions",
        sa.Column(
            "last_webhook_received_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("sharepoint_subscriptions", "last_webhook_received_at")
    op.drop_column("sharepoint_subscriptions", "last_renewal_error")
    op.drop_column("sharepoint_subscriptions", "last_renewal_failed_at")
    op.drop_column("sharepoint_subscriptions", "consecutive_renewal_failures")
