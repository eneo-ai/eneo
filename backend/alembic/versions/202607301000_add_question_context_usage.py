"""store final request context usage

Revision ID: 202607301000
Revises: 202607281600
Create Date: 2026-07-30 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607301000"
down_revision: str | None = "202607281600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("context_prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "questions",
        sa.Column("context_completion_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "questions",
        sa.Column("skill_context_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "skill_context_tokens")
    op.drop_column("questions", "context_completion_tokens")
    op.drop_column("questions", "context_prompt_tokens")
