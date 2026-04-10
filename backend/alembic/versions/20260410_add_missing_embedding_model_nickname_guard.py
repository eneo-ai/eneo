"""ensure embedding model nickname column exists

Revision ID: 20260410_embed_nick_guard
Revises: 20260410_fav_prov_guard
Create Date: 2026-04-10 09:05:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_embed_nick_guard"
down_revision = "20260410_fav_prov_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Repair stamped databases where the canonical 20260319_add_nickname
    # migration is considered applied but the physical embedding_models.nickname
    # column is still absent.
    op.execute(
        """
        ALTER TABLE embedding_models
        ADD COLUMN IF NOT EXISTS nickname varchar
        """
    )
    op.execute(
        """
        UPDATE embedding_models
        SET nickname = SUBSTRING(description FROM 15)
        WHERE nickname IS NULL
          AND description LIKE 'Tenant model: %'
        """
    )
    op.execute(
        """
        UPDATE embedding_models
        SET nickname = name
        WHERE nickname IS NULL
        """
    )


def downgrade() -> None:
    # No-op intentionally: the column is owned by the earlier canonical
    # 20260319_add_nickname migration. This guard only repairs drifted DBs.
    pass
