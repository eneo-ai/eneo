"""Merge insights indexes and token split heads

Revision ID: merge_insights_token_split
Revises: 9d2a6c01f3e7, 20260303_split_token_limit
Create Date: 2026-03-03

"""

from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = "merge_insights_token_split"
down_revision = ("9d2a6c01f3e7", "20260303_split_token_limit")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
