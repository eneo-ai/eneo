"""Add folder selection fields to integration_knowledge

Revision ID: 202411041400
Revises: c3a204ea4300
Create Date: 2025-11-04 14:00:00.000000

Adds support for folder-scoped SharePoint syncing:
- folder_id: SharePoint folder ID for scoped syncing
- folder_path: Human-readable folder path for UI
- selected_item_type: Type of selection (site_root, folder, file)
"""

from alembic import op
import sqlalchemy as sa


revision = "202411041400"
down_revision = "c3a204ea4300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("folder_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("folder_path", sa.String(1024), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("selected_item_type", sa.String(50), nullable=True, server_default="site_root"),
    )
    op.create_index(
        "ix_integration_knowledge_folder_id",
        "integration_knowledge",
        ["folder_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_integration_knowledge_folder_id", table_name="integration_knowledge")
    op.drop_column("integration_knowledge", "selected_item_type")
    op.drop_column("integration_knowledge", "folder_path")
    op.drop_column("integration_knowledge", "folder_id")
