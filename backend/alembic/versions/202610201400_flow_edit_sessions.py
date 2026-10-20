"""flow edit sessions

A user's edit mode on a flow is a row per flow and user, kept from the
moment they press edit until they leave. The chat's write tools and the
panel's save refuse while the caller has no row. Rows never expire; they go
with the flow.

Revision ID: 202610201400
Revises: 202610201300
Create Date: 2026-10-20 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "202610201400"
down_revision: str | None = "202610201300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flow_edit_sessions",
        sa.Column(
            "flow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("flow_id", "user_id", name="pk_flow_edit_sessions"),
    )


def downgrade() -> None:
    op.drop_table("flow_edit_sessions")
