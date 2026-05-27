"""add input/output cost columns to model tables

Adds optional USD cost columns so admins can record (and we can display) the
indicative price of each model. Token-based costs are stored as `NUMERIC(20, 12)`
to preserve precision down to fractions of a cent per token (modern frontier
models are priced in 1e-7 USD/token territory).

Token-based modes (chat/completion + embedding):
  - input_cost_per_token
  - output_cost_per_token

Per-minute mode (transcription) gets its own column rather than reusing the
token columns, since the underlying ratecard is structured differently:
  - cost_per_minute

All columns are nullable. Self-hosted/unknown providers are expected to leave
them unset; the UI displays an em-dash and excludes the model from cost
aggregation when any contributing rate is missing.

Revision ID: 20260430_add_model_costs
Revises: 20260403_cleanup_history
Create Date: 2026-04-30 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "20260430_add_model_costs"
down_revision = "20260403_cleanup_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Token-based cost on completion + embedding tables.
    for table in ("completion_models", "embedding_models"):
        op.add_column(
            table,
            sa.Column("input_cost_per_token", sa.Numeric(20, 12), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("output_cost_per_token", sa.Numeric(20, 12), nullable=True),
        )

    # Transcription is priced per minute of audio. Six decimals is enough for
    # any provider we've seen (Whisper is 0.006 USD/min).
    op.add_column(
        "transcription_models",
        sa.Column("cost_per_minute", sa.Numeric(20, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcription_models", "cost_per_minute")
    for table in ("completion_models", "embedding_models"):
        op.drop_column(table, "output_cost_per_token")
        op.drop_column(table, "input_cost_per_token")
