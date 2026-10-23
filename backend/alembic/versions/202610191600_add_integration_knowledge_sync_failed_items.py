"""integration knowledge sync failed items

A SharePoint sync that could not finish some items keeps its delta token and
retries them by id at the next pass. The items, how often they failed and
when they were set aside are kept on the knowledge row, written in the sync's
own transaction, so they commit and roll back with the documents and the token
they are kept for.

A nullable column without a default is added without rewriting the table.

Revision ID: 202610191600
Revises: 202610191500
Create Date: 2026-10-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610191600"
down_revision: str | None = "202610191500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("sync_failed_items", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_knowledge", "sync_failed_items")
