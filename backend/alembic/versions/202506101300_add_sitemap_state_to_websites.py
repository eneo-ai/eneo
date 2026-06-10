"""add sitemap_state to websites

Revision ID: c4f2a8e71b05
Revises: b3f9a2e81c04
Create Date: 2026-06-10 13:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = "c4f2a8e71b05"
down_revision = "b3f9a2e81c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "websites",
        sa.Column(
            "sitemap_state",
            JSONB(),
            nullable=True,
            comment=(
                "Sitemap fingerprint from the last completed crawl "
                "(hash over url+lastmod entries); scheduled sitemap crawls are "
                "skipped while the fingerprint is unchanged"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("websites", "sitemap_state")
