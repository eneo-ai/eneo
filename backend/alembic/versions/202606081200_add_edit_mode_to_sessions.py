"""Add edit_mode flag to sessions.

Edit-mode conversations (configure an assistant by chatting with it) still need a
persisted session so the multi-turn chat, messages and elicitations work — but they
should never appear in the conversation history list. This adds an ``edit_mode``
boolean that the session-list queries filter out; direct session loads are unaffected.

Revision ID: 202606081200
Revises: 202606081100
Create Date: 2026-06-08
"""

import sqlalchemy as sa

from alembic import op

revision = "202606081200"
down_revision = "202606081100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "edit_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "edit_mode")
