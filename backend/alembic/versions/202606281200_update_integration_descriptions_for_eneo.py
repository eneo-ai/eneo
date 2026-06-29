"""update integration descriptions for Eneo

Revision ID: 202606281200
Revises: 202606251200
Create Date: 2026-06-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "202606281200"
down_revision: Union[str, None] = "202606251200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONFLUENCE_DESCRIPTION = (
    "This integration enables the seamless import of knowledge from Confluence "
    "spaces into Eneo and keeps it up-to-date."
)
SHAREPOINT_DESCRIPTION = (
    "This integration enables the seamless import knowledge of different forms "
    "from Sharepoint into Eneo."
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE integrations
        SET description = '{CONFLUENCE_DESCRIPTION}'
        WHERE "name" = 'Confluence';
        """
    )
    op.execute(
        f"""
        UPDATE integrations
        SET description = '{SHAREPOINT_DESCRIPTION}'
        WHERE "name" = 'Sharepoint';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE integrations
        SET description = 'This integration enables the seamless import of knowledge from Confluence spaces into Eneo and keeps it up-to-date.'
        WHERE "name" = 'Confluence';
        """
    )
    op.execute(
        """
        UPDATE integrations
        SET description = 'This integration enables the seamless import knowledge of different forms from Sharepoint into Eneo.'
        WHERE "name" = 'Sharepoint';
        """
    )
