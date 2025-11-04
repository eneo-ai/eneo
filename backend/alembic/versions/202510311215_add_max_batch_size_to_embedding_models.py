"""Add max_batch_size to embedding models

Revision ID: embed_max_batch_size
Revises: 3914e3c83f18
Create Date: 2025-10-31 12:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "embed_max_batch_size"
down_revision = "3914e3c83f18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "embedding_models",
        sa.Column("max_batch_size", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_embedding_models_max_batch_size_range",
        "embedding_models",
        "max_batch_size IS NULL OR (max_batch_size >= 1 AND max_batch_size <= 256)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_embedding_models_max_batch_size_range",
        "embedding_models",
        type_="check",
    )
    op.drop_column("embedding_models", "max_batch_size")
