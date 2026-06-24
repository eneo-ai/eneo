"""add http_etag and http_last_modified to info_blobs

Revision ID: b3f9a2e81c04
Revises: 202606151000
Create Date: 2026-06-15 11:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "b3f9a2e81c04"
down_revision = "202606151000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "info_blobs",
        sa.Column(
            "http_etag",
            sa.Text(),
            nullable=True,
            comment="ETag from the crawl fetch, sent as If-None-Match on recrawl",
        ),
    )
    op.add_column(
        "info_blobs",
        sa.Column(
            "http_last_modified",
            sa.Text(),
            nullable=True,
            comment="Last-Modified from the crawl fetch, sent as If-Modified-Since on recrawl",
        ),
    )


def downgrade() -> None:
    op.drop_column("info_blobs", "http_last_modified")
    op.drop_column("info_blobs", "http_etag")
