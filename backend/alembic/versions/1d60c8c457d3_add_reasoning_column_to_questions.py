"""add reasoning column to questions

Persist the model's reasoning/thinking text on each question so the
reasoning trace can be re-shown when a conversation is reloaded, instead
of only existing transiently in the SSE stream.

Revision ID: 1d60c8c457d3
Revises: b3916fa5aac6
Create Date: 2026-06-11 09:56:34.222627
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = '1d60c8c457d3'
down_revision = 'b3916fa5aac6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("reasoning", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "reasoning")
