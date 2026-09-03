"""add bounded File/Icon backfill resume state

Revision ID: 202608261800
Revises: 202608251400
Create Date: 2026-08-26 18:00:00.000000

The worker stores the last operator-provided resume revision and a durable
ledger cursor on the campaign. Failed items record the revision in which they
failed. A strictly higher value can therefore requeue the older failures in
bounded batches without allowing a stale value or a repeated failure to create
an infinite retry loop.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608261800"
down_revision: str | None = "202608251400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_icon_backfill_campaign",
        sa.Column(
            "resume_revision",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_file_icon_backfill_campaign_resume_revision",
        "file_icon_backfill_campaign",
        "resume_revision >= 0",
    )
    op.add_column(
        "file_icon_backfill_campaign",
        sa.Column("resume_cursor_id", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_file_icon_backfill_campaign_resume_cursor",
        "file_icon_backfill_campaign",
        "resume_cursor_id IS NULL OR (resume_cursor_id >= 0 AND state = 'active')",
    )
    op.add_column(
        "file_icon_backfill_items",
        sa.Column("failure_revision", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_file_icon_backfill_items_failure_revision",
        "file_icon_backfill_items",
        "(state = 'failed') = (failure_revision IS NOT NULL) AND "
        "(failure_revision IS NULL OR failure_revision >= 0)",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon adoption may already have resumed and created durable "
        "object-content references. Recover forward or restore the coordinated "
        "pre-upgrade backup."
    )
