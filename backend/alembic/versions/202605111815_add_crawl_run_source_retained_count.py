"""add_crawl_run_source_retained_count

Revision ID: 202605111815
Revises: 202605111230
Create Date: 2026-05-11 18:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605111815"
down_revision: Union[str, None] = "202605111230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "pages_source_retained",
            sa.Integer(),
            nullable=True,
            comment="Sitemap page URLs retained without downloading during source skip",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "pages_source_retained")
