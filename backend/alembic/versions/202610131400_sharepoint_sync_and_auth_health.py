"""SharePoint sync and credential health

Integration knowledge records the outcome of its last sync attempt so the
space UI can tell a failing or empty integration from a healthy one.
Tenant SharePoint apps record the last credential failure and success so the
admin page can show an expired secret or revoked refresh token.
Subscriptions remember the notification URL they were registered with so a
changed Eneo origin can be detected at renewal.

Revision ID: 202610131400
Revises: 202610131300
Create Date: 2026-10-13

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610131400"
down_revision = "202610131300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column(
            "last_sync_status",
            sa.Text(),
            nullable=False,
            server_default="never",
        ),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("last_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("last_sync_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing rows with a sync timestamp have synced successfully at least once.
    op.execute(
        "UPDATE integration_knowledge SET last_sync_status = 'success', "
        "last_sync_attempted_at = last_synced_at WHERE last_synced_at IS NOT NULL"
    )

    op.add_column(
        "tenant_sharepoint_apps",
        sa.Column("last_auth_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant_sharepoint_apps",
        sa.Column("last_auth_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_sharepoint_apps",
        sa.Column("last_auth_success_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "sharepoint_subscriptions",
        sa.Column("notification_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sharepoint_subscriptions", "notification_url")
    op.drop_column("tenant_sharepoint_apps", "last_auth_success_at")
    op.drop_column("tenant_sharepoint_apps", "last_auth_error_at")
    op.drop_column("tenant_sharepoint_apps", "last_auth_error")
    op.drop_column("integration_knowledge", "last_sync_attempted_at")
    op.drop_column("integration_knowledge", "last_sync_error")
    op.drop_column("integration_knowledge", "last_sync_status")
