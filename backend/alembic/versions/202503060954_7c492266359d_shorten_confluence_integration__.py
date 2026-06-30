# flake8: noqa

"""Shorten confluence integration description
Revision ID: 7c492266359d
Revises: 22e39d7c9fa4
Create Date: 2025-03-06 09:54:59.503625
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "7c492266359d"
down_revision = "22e39d7c9fa4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE integrations
        SET description = 'This integration enables the seamless import of knowledge from Confluence spaces into Eneo and keeps it up-to-date.'
        WHERE "name" = 'Confluence';
    """
    )


def downgrade() -> None:
    pass
