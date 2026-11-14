"""Add external_clients_description to assistants.

Revision ID: 202611141400
Revises: 202611141300
What other systems should know about an assistant, when that is not what its
own users read in the description. Null for every existing assistant, which
keeps offering its description. Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611141400"
down_revision: str = "202611141300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column("external_clients_description", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assistants", "external_clients_description")
