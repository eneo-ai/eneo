"""add crawl run terminal source

Revision ID: 202605191100
Revises: 202605181000
Create Date: 2026-05-19 11:00:00.000000

Historical crawl runs intentionally stay NULL. Source-specific admin views
must only trust explicit post-migration values instead of backfilling from
outcome codes, because workers and the watchdog can emit the same outcomes.

No partial index is added here. Existing tenant/window predicates remain the
primary query boundary; add a measured source-specific index only if production
plans show the new predicate is material at crawl_runs scale.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605191100"
down_revision: Union[str, None] = "202605181000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CRAWL_RUNS_TERMINAL_SOURCE_CHECK = "ck_crawl_runs_terminal_source"


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "terminal_source",
            sa.Text(),
            nullable=True,
            comment=(
                "Source that committed the terminal outcome; NULL for historical "
                "rows before terminal attribution was captured"
            ),
        ),
    )
    op.create_check_constraint(
        CRAWL_RUNS_TERMINAL_SOURCE_CHECK,
        "crawl_runs",
        "terminal_source IS NULL OR terminal_source IN ('admin', 'crawler', 'queue', 'watchdog')",
    )


def downgrade() -> None:
    op.drop_constraint(
        CRAWL_RUNS_TERMINAL_SOURCE_CHECK,
        "crawl_runs",
        type_="check",
    )
    op.drop_column("crawl_runs", "terminal_source")
