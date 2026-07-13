"""Add storage_key column to files.

Revision ID: 202606061001
Revises: 202607071200
Create Date: 2026-06-06
"""

import sqlalchemy as sa

from alembic import op

revision = "202606061001"
down_revision = "202607071200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("storage_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "storage_key")
