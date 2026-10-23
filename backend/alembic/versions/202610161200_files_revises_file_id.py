"""files.revises_file_id: a user-saved version of a conversation document

A Markdown document the assistant made is read, and now edited, in Eneo.
Saving the edit stores a new File that points at the version it was made
from, so the conversation can chain versions and the model is told which one
is current. ON DELETE SET NULL: a version outlives the file it revised and then
stands as its own document. Not ``parent_file_id``, which means "derived,
deleted with its parent".

Revision ID: 202610161200
Revises: 202610141000
Create Date: 2026-10-16

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610161200"
down_revision = "202610141000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("revises_file_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_files_revises_file_id_files",
        "files",
        "files",
        ["revises_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_files_revises_file_id", "files", ["revises_file_id"])


def downgrade() -> None:
    op.drop_index("ix_files_revises_file_id", table_name="files")
    op.drop_constraint("fk_files_revises_file_id_files", "files", type_="foreignkey")
    op.drop_column("files", "revises_file_id")
