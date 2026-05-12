"""add_crawl_run_file_size_skips

Revision ID: 202605121445
Revises: 202605121305
Create Date: 2026-05-12 14:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605121445"
down_revision: Union[str, None] = "202605121305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "files_too_large_skipped",
            sa.Integer(),
            nullable=True,
            comment=(
                "Files skipped because Scrapy stopped the download at DOWNLOAD_MAXSIZE"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "files_too_large_skipped")
