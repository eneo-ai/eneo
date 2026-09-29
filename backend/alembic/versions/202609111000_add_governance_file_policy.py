"""add governance file policy

Revision ID: 202609111000
Revises: 202609071000
Create Date: 2026-09-11 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609111000"
down_revision: str | None = "202609071000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL keeps the dimension ungoverned: every personal assistant keeps
    # inlining attachment text exactly as before this column existed.
    op.add_column(
        "governance_policies",
        sa.Column("inline_file_text", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("governance_policies", "inline_file_text")
