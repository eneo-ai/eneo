"""add description column to collections (groups table)

Revision ID: 20260324_collection_desc
Revises: 20260319_add_nickname
Create Date: 2026-03-24
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260324_collection_desc"
down_revision = "20260319_add_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column("description", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("groups", "description")
