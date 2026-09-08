"""track optional File/Icon legacy cleanup without removing upgrade sources

Revision ID: 202609081400
Revises: 202609071000

An earlier unmerged development version of this revision removed legacy columns
and migration tables. Databases that applied it must restore their pre-cleanup
backup; changing the revision stamp cannot restore those bytes or tables.
"""

import sqlalchemy as sa
from alembic import op

revision = "202609081400"
down_revision = "202609071000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_icon_backfill_admission_state",
        sa.Column("legacy_cleaned_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT legacy_cleaned_at IS NOT NULL FROM file_icon_backfill_admission_state WHERE singleton"
        )
    ):
        raise RuntimeError(
            "Legacy File/Icon columns have been cleaned. Restore the coordinated pre-cleanup backup before downgrading."
        )
    op.drop_column("file_icon_backfill_admission_state", "legacy_cleaned_at")
