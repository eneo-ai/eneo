"""add file content storage columns

Revision ID: 202606271300
Revises: 202606251200
Create Date: 2026-06-27 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202606271300"
down_revision: Union[str, None] = "202606251200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable + no server_default: existing rows stay NULL, which the dual-read
    # path treats as "the bytes live inline in files.blob" (current behaviour).
    # The blob column is intentionally NOT dropped — it stays the default store.
    op.add_column("files", sa.Column("storage_backend", sa.String(), nullable=True))
    op.add_column("files", sa.Column("storage_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "storage_key")
    op.drop_column("files", "storage_backend")
