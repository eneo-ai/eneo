"""gate File/Icon recovery through cumulative inline capacity

Revision ID: 202608281130
Revises: 202608281000
Create Date: 2026-08-28 11:30:00.000000

Rows satisfied by existing available references were excluded from the initial
inline capacity decision. Track which ledger bytes have been admitted and the
campaign's cumulative approved total so a later backend-failure recovery must
pass the same capacity gate before it can copy those legacy bytes inline.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608281130"
down_revision: str | None = "202608281000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_icon_backfill_items",
        sa.Column(
            "capacity_admitted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "file_icon_backfill_campaign",
        sa.Column(
            "capacity_admitted_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_file_icon_backfill_campaign_capacity_admitted",
        "file_icon_backfill_campaign",
        "capacity_admitted_bytes >= 0",
        postgresql_not_valid=True,
    )

    op.execute(
        """
        UPDATE file_icon_backfill_items
        SET capacity_admitted = true
        WHERE EXISTS (SELECT 1 FROM file_icon_backfill_campaign)
          AND (
              state IN ('ready', 'leased')
              OR (
                  attempts > 0
                  AND NOT (
                      state = 'failed'
                      AND last_error_code IN ('backend_missing', 'backend_corrupt')
                  )
              )
          );

        UPDATE file_icon_backfill_campaign
        SET capacity_admitted_bytes = COALESCE((
            SELECT sum(payload_size_estimate)
            FROM file_icon_backfill_items
            WHERE state IN ('ready', 'leased') OR attempts > 0
        ), 0);
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon recovery capacity may already have been admitted. Recover "
        "forward or restore the coordinated pre-upgrade backup."
    )
