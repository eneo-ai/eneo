"""Add sharepoint_item_id to info_blobs

Revision ID: 202411041401
Revises: 202411041400
Create Date: 2025-11-04 14:01:00.000000

Adds unique SharePoint item ID to info_blobs for:
- Delta sync updates: identify which file changed
- Webhook handling: correctly identify changed items
- Deduplication: handle duplicate filenames across folders
"""

from alembic import op
import sqlalchemy as sa


revision = "202411041401"
down_revision = "202411041400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "info_blobs",
        sa.Column("sharepoint_item_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("info_blobs", "sharepoint_item_id")
