"""add show_model_pricing to tenants
Revision ID: 202606151000
Revises: 202605251000
Create Date: 2026-06-15 10:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202606151000"
down_revision = "202605251000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default true preserves the existing behaviour (prices visible) for all
    # current tenants; admins opt out per organization.
    op.add_column(
        "tenants",
        sa.Column(
            "show_model_pricing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "show_model_pricing")
