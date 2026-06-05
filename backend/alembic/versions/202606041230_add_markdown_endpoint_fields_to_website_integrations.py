"""add markdown endpoint fields to website integration configs

Revision ID: 202606041230
Revises: 202606041100
Create Date: 2026-06-04 12:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202606041230"
down_revision = "202606041100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "website_integration_configs",
        sa.Column(
            "markdown_endpoint_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'get'"),
        ),
    )
    op.add_column(
        "website_integration_configs",
        sa.Column(
            "markdown_endpoint_url_location",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'query'"),
        ),
    )
    op.add_column(
        "website_integration_configs",
        sa.Column(
            "markdown_endpoint_url_param_name",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'url'"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "website_integration_configs", "markdown_endpoint_url_param_name"
    )
    op.drop_column(
        "website_integration_configs", "markdown_endpoint_url_location"
    )
    op.drop_column("website_integration_configs", "markdown_endpoint_method")
