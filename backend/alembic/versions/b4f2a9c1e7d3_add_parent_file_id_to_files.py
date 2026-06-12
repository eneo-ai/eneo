"""add parent_file_id to files
Revision ID: b4f2a9c1e7d3
Revises: 202606111200
Create Date: 2026-06-11 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "b4f2a9c1e7d3"
down_revision = "202606111200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column(
            "parent_file_id",
            sa.UUID(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_files_parent_file_id", "files", ["parent_file_id"])


def downgrade() -> None:
    op.drop_index("ix_files_parent_file_id", table_name="files")
    op.drop_column("files", "parent_file_id")
