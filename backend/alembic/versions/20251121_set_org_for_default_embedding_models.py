# flake8: noqa

"""set org for default embedding models
Revision ID: 20251121_set_embedding_org
Revises: 20251119_e5_berget
Create Date: 2025-11-21 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = '20251121_set_embedding_org'
down_revision = '20251119_e5_berget'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set org for the default embedding models created in migration 2c573133f9b6
    # This migration is safe to run at any point because it only updates models
    # where org IS NULL
    conn = op.get_bind()

    # Set OpenAI as org for text-embedding-3-small
    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = 'OpenAI'
            WHERE name = 'text-embedding-3-small' AND org IS NULL
        """)
    )

    # Set OpenAI as org for text-embedding-ada-002
    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = 'OpenAI'
            WHERE name = 'text-embedding-ada-002' AND org IS NULL
        """)
    )

    # Set Berget as org for multilingual-e5-large
    # Note: An earlier migration (20251119_e5_berget) updates this from Microsoft to Berget,
    # but on fresh installs it was NULL, so we set it to Berget directly
    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = 'Berget'
            WHERE name = 'multilingual-e5-large' AND org IS NULL
        """)
    )


def downgrade() -> None:
    # Set org back to NULL for these models
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            UPDATE embedding_models
            SET org = NULL
            WHERE name IN ('text-embedding-3-small', 'text-embedding-ada-002', 'multilingual-e5-large')
            AND org IN ('OpenAI', 'Berget')
        """)
    )
