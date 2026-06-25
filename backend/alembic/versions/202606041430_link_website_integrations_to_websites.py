"""link website integrations to websites

Revision ID: 202606041430
Revises: 202606041300
Create Date: 2026-06-04 14:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202606041430"
down_revision: Union[str, None] = "202606041300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "website_integration_configs",
        sa.Column("website_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f("ix_website_integration_configs_website_id"),
        "website_integration_configs",
        ["website_id"],
        unique=True,
    )
    op.create_foreign_key(
        "website_integration_configs_website_id_fkey",
        "website_integration_configs",
        "websites",
        ["website_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "website_integration_configs_website_id_fkey",
        "website_integration_configs",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_website_integration_configs_website_id"),
        table_name="website_integration_configs",
    )
    op.drop_column("website_integration_configs", "website_id")
