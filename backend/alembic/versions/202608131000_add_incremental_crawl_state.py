"""add incremental crawler state

Revision ID: 202608131000
Revises: 202608121500
Create Date: 2026-08-13 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202608131000"
down_revision: str | None = "202608121500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "info_blobs",
        sa.Column(
            "http_etag",
            sa.Text(),
            nullable=True,
            comment="ETag sent as If-None-Match on the next crawl",
        ),
    )
    op.add_column(
        "info_blobs",
        sa.Column(
            "http_last_modified",
            sa.Text(),
            nullable=True,
            comment="Last-Modified sent as If-Modified-Since on the next crawl",
        ),
    )
    op.add_column(
        "websites",
        sa.Column(
            "sitemap_state",
            JSONB(),
            nullable=True,
            comment="Fingerprint and timestamp of the last complete sitemap crawl",
        ),
    )


def downgrade() -> None:
    op.drop_column("websites", "sitemap_state")
    op.drop_column("info_blobs", "http_last_modified")
    op.drop_column("info_blobs", "http_etag")
