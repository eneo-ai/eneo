"""add icons table and icon_id to assistants, spaces and apps

Revision ID: 20251127_add_icons
Revises: 20251121_set_embedding_org
Create Date: 2025-11-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, UUID

from alembic import op

# revision identifiers, used by Alembic
revision = "20251127_add_icons"
down_revision = "20251121_set_embedding_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create icons table
    op.create_table(
        "icons",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("blob", BYTEA, nullable=False),
        sa.Column("mimetype", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
    )

    # Add icon_id to assistants table
    op.add_column("assistants", sa.Column("icon_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_assistants_icon_id",
        "assistants",
        "icons",
        ["icon_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add icon_id to spaces table
    op.add_column("spaces", sa.Column("icon_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_spaces_icon_id",
        "spaces",
        "icons",
        ["icon_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add icon_id to apps table
    op.add_column("apps", sa.Column("icon_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_apps_icon_id",
        "apps",
        "icons",
        ["icon_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove from apps table
    op.drop_constraint("fk_apps_icon_id", "apps", type_="foreignkey")
    op.drop_column("apps", "icon_id")

    # Remove from spaces table
    op.drop_constraint("fk_spaces_icon_id", "spaces", type_="foreignkey")
    op.drop_column("spaces", "icon_id")

    # Remove from assistants table
    op.drop_constraint("fk_assistants_icon_id", "assistants", type_="foreignkey")
    op.drop_column("assistants", "icon_id")

    # Drop icons table
    op.drop_table("icons")
