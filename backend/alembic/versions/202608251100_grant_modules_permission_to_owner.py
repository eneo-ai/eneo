"""grant modules permission to existing Owner roles

Revision ID: 202608251100
Revises: 202608251000
Create Date: 2026-08-20 15:00:00.000000

Module installation becomes a session-backed organization permission. New
organizations receive it from the predefined Owner template; this migration
converges existing Owner roles. Custom roles remain unchanged so delegation is
always explicit.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608251100"
down_revision: str = "202608251000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_append(permissions, 'modules') "
            "WHERE predefined_source = 'Owner' "
            "AND NOT ('modules' = ANY(permissions))"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_remove(permissions, 'modules') "
            "WHERE predefined_source = 'Owner'"
        )
    )
