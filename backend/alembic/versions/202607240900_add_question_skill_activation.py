"""add Question Skill activation evidence

Revision ID: 202607240900
Revises: 202607231700
Create Date: 2026-07-24 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607240900"
down_revision: str | None = "202607231700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "skill_activation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "skill_activation")
