"""add_composite_index_info_blob_chunks_blob_id_chunk_no
Revision ID: 92f07192cdb6
Revises: 9d2a6c01f3e7
Create Date: 2026-03-04 12:57:33.613597
"""

from alembic import op


# revision identifiers, used by Alembic
revision = '92f07192cdb6'
down_revision = '9d2a6c01f3e7'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_index(
        "ix_info_blob_chunks_blob_id_chunk_no",
        "info_blob_chunks",
        ["info_blob_id", "chunk_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_info_blob_chunks_blob_id_chunk_no", table_name="info_blob_chunks")