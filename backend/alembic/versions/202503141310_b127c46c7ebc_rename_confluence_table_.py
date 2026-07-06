# flake8: noqa

"""Rename confluence table
Revision ID: b127c46c7ebc
Revises: b8f9452a548a
Create Date: 2025-03-11 13:10:34.161932
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "b127c46c7ebc"
down_revision = "b8f9452a548a"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("confluence_tokens", "oauth_tokens")
    # Fix the default token type
    op.execute(
        """
        UPDATE oauth_tokens set token_type = 'confluence';
    """
    )

    # Roll out the sharepoint integration
    op.execute(
        """
        INSERT INTO integrations ("name",description,integration_type) VALUES
            ('Sharepoint','This integration enables the seamless import knowledge of different forms from Sharepoint into Eneo.','sharepoint');
    """
    )


def downgrade():
    # Drop the oauth_tokens table if necessary
    op.rename_table("oauth_tokens", "confluence_tokens")

    # remove integration
    op.execute("""delete  from integrations i where i.name = 'Sharepoint'""")
