"""Keep the source-run identity needed to resume an audio-family proof."""

import sqlalchemy as sa

from alembic import op

revision = "202610061900"
down_revision = "202610061800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "gallring_receipts", sa.Column("source_run_id", sa.UUID(), nullable=True)
    )
    op.drop_constraint(
        "ck_gallring_receipts_category", "gallring_receipts", type_="check"
    )
    op.create_check_constraint(
        "ck_gallring_receipts_category",
        "gallring_receipts",
        "category IN ('abandoned_upload','template_asset','run_record','audio_after_use')",
    )
    op.create_check_constraint(
        "ck_retention_receipts_audio_source",
        "gallring_receipts",
        "category <> 'audio_after_use' OR source_run_id IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Existing audio proofs intentionally prevent a downgrade that would lose their source.
    op.drop_constraint(
        "ck_gallring_receipts_category", "gallring_receipts", type_="check"
    )
    op.create_check_constraint(
        "ck_gallring_receipts_category",
        "gallring_receipts",
        "category IN ('abandoned_upload','template_asset','run_record')",
    )
    op.drop_constraint(
        "ck_retention_receipts_audio_source", "gallring_receipts", type_="check"
    )
    op.drop_column("gallring_receipts", "source_run_id")
