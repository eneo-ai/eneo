"""add_crawl_run_hash_retained_counts

Revision ID: 202605121305
Revises: 202605112230
Create Date: 2026-05-12 13:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605121305"
down_revision: Union[str, None] = "202605112230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "pages_hash_retained",
            sa.Integer(),
            nullable=True,
            comment=(
                "Fetched pages retained without re-indexing because content hash and "
                "embedding model matched the existing blob"
            ),
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column(
            "files_hash_retained",
            sa.Integer(),
            nullable=True,
            comment=(
                "Downloaded files retained without re-indexing because content hash and "
                "embedding model matched the existing blob"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "files_hash_retained")
    op.drop_column("crawl_runs", "pages_hash_retained")
