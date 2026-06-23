"""align model tables: add nickname + deleted_at parity

Phase 1 of the model-table alignment (docs/plans/model-table-alignment).
Purely additive — no behaviour change. Brings the three model tables to a
parallel shape so later phases (display-name uniqueness, unified soft-delete)
can be built once instead of three times:

  - transcription_models gains `nickname` (display name), backfilled from the
    current `name` so end users see an identical label. Note: transcription
    still writes the display name to `name` today (model_name holds the API id);
    `nickname` is unused until a later phase switches the source of truth.
  - embedding_models and transcription_models gain `deleted_at` for soft-delete
    parity with completion_models (nullable, indexed, unused for now).

Revision ID: 20260601_align_model_tables
Revises: 20260501_backfill_model_costs
Create Date: 2026-06-01

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "20260601_align_model_tables"
down_revision = "202605261000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # transcription_models: add display-name column, backfill from name so the
    # label users see is unchanged.
    op.add_column(
        "transcription_models",
        sa.Column("nickname", sa.String(), nullable=True),
    )
    op.execute(
        "UPDATE transcription_models SET nickname = name WHERE nickname IS NULL"
    )

    # Soft-delete parity with completion_models (which already has deleted_at).
    op.add_column(
        "embedding_models",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_embedding_models_deleted_at", "embedding_models", ["deleted_at"]
    )
    op.add_column(
        "transcription_models",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_transcription_models_deleted_at",
        "transcription_models",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transcription_models_deleted_at", table_name="transcription_models"
    )
    op.drop_column("transcription_models", "deleted_at")

    op.drop_index(
        "ix_embedding_models_deleted_at", table_name="embedding_models"
    )
    op.drop_column("embedding_models", "deleted_at")

    op.drop_column("transcription_models", "nickname")
