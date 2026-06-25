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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("website_integration_configs")
    }

    if "markdown_endpoint_method" not in existing_columns:
        op.add_column(
            "website_integration_configs",
            sa.Column(
                "markdown_endpoint_method",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'get'"),
            ),
        )
    if "markdown_endpoint_url_location" not in existing_columns:
        op.add_column(
            "website_integration_configs",
            sa.Column(
                "markdown_endpoint_url_location",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'query'"),
            ),
        )
    if "markdown_endpoint_url_param_name" not in existing_columns:
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("website_integration_configs")
    }

    if "markdown_endpoint_url_param_name" in existing_columns:
        op.drop_column(
            "website_integration_configs", "markdown_endpoint_url_param_name"
        )
    if "markdown_endpoint_url_location" in existing_columns:
        op.drop_column(
            "website_integration_configs", "markdown_endpoint_url_location"
        )
    if "markdown_endpoint_method" in existing_columns:
        op.drop_column("website_integration_configs", "markdown_endpoint_method")
