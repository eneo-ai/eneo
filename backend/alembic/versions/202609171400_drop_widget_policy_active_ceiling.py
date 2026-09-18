"""drop the active-widget ceiling from tenant widget policies

Revision ID: 202609171400
Revises: 202609171300
Create Date: 2026-09-17 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609171400"
down_revision: str | None = "202609171300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The ceiling was replaced by the admin overview; the model ignores the
    # key already, this just keeps stored policies tidy.
    op.execute(
        sa.text(
            "UPDATE tenants SET widget_policy = widget_policy - 'max_active_widgets' "
            "WHERE widget_policy ? 'max_active_widgets'"
        )
    )


def downgrade() -> None:
    pass
