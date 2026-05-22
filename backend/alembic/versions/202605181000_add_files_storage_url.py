"""files.storage_url: persist external file-storage URL alongside extracted text

Eneo's file processor extracts text from documents on upload and drops the
original bytes. That makes eneo unable to hand a downstream consumer
(eg an MCP server's ``ingest_url`` tool) the real PDF/DOCX/etc. We now
also push the raw bytes to an external file-storage service (today
Ladan) at upload time and persist the returned URL on the file
row, so chat turns can surface that URL without re-uploading and without
trying to reconstruct lost bytes from extracted text.

Nullable: rows persisted before this migration (and uploads that happen
when file_storage_url is unset) keep ``NULL``.

Revision ID: 202605181000
Revises: 202605171000
Create Date: 2026-05-18
"""

import sqlalchemy as sa

from alembic import op

revision = "202605181000"
down_revision = "202605171000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("storage_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "storage_url")
