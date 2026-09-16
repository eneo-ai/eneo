"""Add durable sitemap crawl webhooks.

Revision ID: 202609161000
Revises: 202609101130
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609161000"
down_revision = "202609101130"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "websites", sa.Column("webhook_token_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "websites",
        sa.Column(
            "webhook_pending", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "websites", sa.Column("webhook_started_job_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "crawl_runs", sa.Column("webhook_dispatch", postgresql.JSONB(), nullable=True)
    )
    op.create_index(
        "ix_websites_webhook_pending",
        "websites",
        ["id"],
        postgresql_where=sa.text("webhook_pending = true"),
    )


def downgrade():
    # Older application versions cannot deserialize this interval.
    op.execute(
        "UPDATE websites SET update_interval = 'never' WHERE update_interval = 'webhook'"
    )
    op.drop_index("ix_websites_webhook_pending", table_name="websites")
    op.drop_column("crawl_runs", "webhook_dispatch")
    op.drop_column("websites", "webhook_started_job_id")
    op.drop_column("websites", "webhook_pending")
    op.drop_column("websites", "webhook_token_hash")
