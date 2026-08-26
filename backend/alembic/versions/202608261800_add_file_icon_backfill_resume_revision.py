"""add explicit File/Icon backfill resume revision

Revision ID: 202608261800
Revises: 202608251400
Create Date: 2026-08-26 18:00:00.000000

The worker stores the last operator-provided resume revision on the campaign.
A strictly higher value can requeue failed items once after the cause has been
fixed, without allowing a stale environment value to create an infinite retry
loop.
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


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon adoption may already have resumed and created durable "
        "object-content references. Recover forward or restore the coordinated "
        "pre-upgrade backup."
    )
