"""Add external_clients_enabled to assistants.

Revision ID: 202611141200
Revises: 202611091200
A space admin sets it to let people who may use the assistant find and ask it
from other clients than Eneo's own. Existing assistants get false. Downgrade
drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611141200"
down_revision: str = "202611091200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "external_clients_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "external_clients_enabled")
