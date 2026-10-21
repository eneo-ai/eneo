"""sharepoint subscription lifecycle notification url

Subscriptions remember the lifecycle notification URL they were created with.
Graph accepts ``lifecycleNotificationUrl`` only when a subscription is
created, so a subscription without one is recreated at its next renewal
instead of being renewed in place.

Revision ID: 202610191400
Revises: 202610191030
Create Date: 2026-10-19 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610191400"
down_revision: str | None = "202610191030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sharepoint_subscriptions",
        sa.Column("lifecycle_notification_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sharepoint_subscriptions", "lifecycle_notification_url")
