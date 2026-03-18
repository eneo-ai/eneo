"""add icon_id to group_chats

Revision ID: 20260318_add_icon_id_to_group_chats
Revises: mcp_security_classification
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260318_add_icon_id_to_group_chats"
down_revision = "mcp_security_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_chats",
        sa.Column(
            "icon_id",
            sa.Uuid(),
            sa.ForeignKey("icons.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("group_chats", "icon_id")
