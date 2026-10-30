"""Let a flow authoring chat choose its model and track its last mode change

``completion_model_id`` and ``reasoning_effort`` are the person's own choice
for the chat; null follows the organisation's default for flow chats, then
the space's. ``mode_changed_at`` is when edit mode was last turned on or off:
entering edit mode after a long pause starts a new conversation.

Revision ID: 202610221100
Revises: 202610220930
Create Date: 2026-10-22 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610221100"
down_revision: str | None = "202610220930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flow_authoring_chats",
        sa.Column(
            "completion_model_id",
            sa.UUID(),
            sa.ForeignKey("completion_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "flow_authoring_chats",
        sa.Column("reasoning_effort", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_authoring_chats",
        sa.Column("mode_changed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_authoring_chats", "mode_changed_at")
    op.drop_column("flow_authoring_chats", "reasoning_effort")
    op.drop_column("flow_authoring_chats", "completion_model_id")
