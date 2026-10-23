"""add model_providers.outbound_headers

Per-provider configured outbound HTTP headers. Additive and nullable: NULL means
no headers, so every existing provider sends exactly what it sent before.

Revision ID: 202609281100
Revises: 202609281000
Create Date: 2026-09-28 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202609281100"
down_revision: str | None = "202609281000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_providers",
        sa.Column(
            "outbound_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # DATA LOSS: drops every configured outbound header, including encrypted
    # secret values that cannot be recovered from anywhere else. Administrators
    # re-enter them after upgrading again.
    op.drop_column("model_providers", "outbound_headers")
