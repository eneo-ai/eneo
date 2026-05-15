"""add_crawl_run_too_large_file_samples

Revision ID: 202605152115
Revises: 202605142300
Create Date: 2026-05-15 21:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605152115"
down_revision: Union[str, None] = "202605142300"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "files_too_large_download_limit_bytes",
            sa.Integer(),
            nullable=True,
            comment="Resolved DOWNLOAD_MAXSIZE value used when file-size skips occurred",
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column(
            "files_too_large_samples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Capped file URLs and observed sizes skipped by DOWNLOAD_MAXSIZE",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "files_too_large_samples")
    op.drop_column("crawl_runs", "files_too_large_download_limit_bytes")
