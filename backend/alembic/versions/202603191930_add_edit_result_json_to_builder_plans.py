"""add_edit_result_json_to_builder_plans

Store the compiled edit result (diff, advisories, confidence) alongside
the plan spec so that it survives page reloads and can be served via
REST GET /plans/{plan_id} without requiring the SSE stream.

Revision ID: 202603191930
Revises: 202603151045
Create Date: 2026-03-19 19:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202603191930"
down_revision = "202603151045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "builder_plans",
        sa.Column("edit_result_json", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("builder_plans", "edit_result_json")
