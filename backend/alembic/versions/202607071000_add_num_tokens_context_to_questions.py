"""Add num_tokens_context column to questions.

Revision ID: 202607071000
Revises: 202607061000
Create Date: 2026-07-07
"""

import sqlalchemy as sa

from alembic import op

revision = "202607071000"
down_revision = "202607061000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "num_tokens_context",
            sa.Integer(),
            nullable=True,
            comment=(
                "Prompt tokens of the turn's final LLM call (context-window "
                "occupancy); num_tokens_question sums every call of a "
                "multi-round tool turn"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "num_tokens_context")
