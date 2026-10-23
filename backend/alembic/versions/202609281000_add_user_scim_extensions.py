"""add users.scim_extensions

Stores the SCIM Enterprise User extension (RFC 7643 §4.3), keyed by schema URN.
Additive and nullable: no backfill, no index — nothing queries it.

Revision ID: 202609281000
Revises: 202610051000
Create Date: 2026-09-28 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202609281000"
down_revision: str | None = "202610051000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "scim_extensions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # DATA LOSS: drops the stored SCIM extension attributes. They are
    # IdP-sourced and re-sent by the identity provider on its next full sync,
    # so no Eneo-owned data is lost.
    op.drop_column("users", "scim_extensions")
