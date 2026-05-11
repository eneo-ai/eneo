"""add_crawl_run_outcome_code

Revision ID: 202605111230
Revises: 202605061100
Create Date: 2026-05-11 12:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "202605111230"
down_revision: Union[str, None] = "202605061100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column(
            "outcome_code",
            sa.String(),
            nullable=True,
            comment="Typed crawl/job outcome code for frontend display and diagnostics",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "outcome_code")
