# flake8: noqa

"""update multilingual-e5-large org to Berget
Revision ID: 20251119_e5_berget
Revises: 44bef4e52527
Create Date: 2025-11-19 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = '20251119_e5_berget'
down_revision = '44bef4e52527'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update the multilingual-e5-large embedding model org from Microsoft to Berget
    # This model is now hosted by Berget.ai instead of being Microsoft's model
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = 'Berget'
            WHERE name = 'multilingual-e5-large' AND org = 'Microsoft'
        """)
    )


def downgrade() -> None:
    # Revert back to Microsoft org
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = 'Microsoft'
            WHERE name = 'multilingual-e5-large' AND org = 'Berget'
        """)
    )
