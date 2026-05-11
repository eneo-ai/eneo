"""add_website_source_verified_timestamp

Revision ID: 202605112230
Revises: 202605111815
Create Date: 2026-05-11 22:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605112230"
down_revision: Union[str, None] = "202605111815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Do not backfill from last_crawled_at; legacy crawl timestamps do not prove
    # that the sitemap source frontier was complete and page-clean.
    op.add_column(
        "websites",
        sa.Column(
            "last_source_verified_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Last complete sitemap crawl with no page persistence failures",
        ),
    )


def downgrade() -> None:
    op.drop_column("websites", "last_source_verified_at")
