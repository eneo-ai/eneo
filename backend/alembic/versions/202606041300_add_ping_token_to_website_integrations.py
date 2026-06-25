"""add ping token to website integration configs

Revision ID: 202606041300
Revises: 202606041230
Create Date: 2026-06-04 13:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202606041300"
down_revision = "202606041230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "website_integration_configs",
        sa.Column("ping_token", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE website_integration_configs
        SET ping_token = replace(gen_random_uuid()::text, '-', '')
        WHERE ping_token IS NULL
        """
    )
    op.alter_column(
        "website_integration_configs",
        "ping_token",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.create_index(
        op.f("ix_website_integration_configs_ping_token"),
        "website_integration_configs",
        ["ping_token"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_website_integration_configs_ping_token"),
        table_name="website_integration_configs",
    )
    op.drop_column("website_integration_configs", "ping_token")
