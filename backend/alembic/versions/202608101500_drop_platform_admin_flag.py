"""drop the retired platform-administrator flag

``users.is_platform_admin`` was introduced as the smallest session-backed
authority for the admin storage settings before Eneo had a permission that
fit. Storage administration is now a normal permission (``Permission.STORAGE``,
held by the Owner role by default), and every router enforces that instead, so
the column no longer authorizes anything. Keeping it would leave a second,
grantable source of authority truth that reads as if it still governs access.

This is the contract half of an expand/contract pair: the expand half (no code
reads or writes the column) shipped with the move to ``Permission.STORAGE``.

ROLLING DEPLOY: incompatible. Application instances that still map this column
fail once it is dropped, because SQLAlchemy names every mapped column in its
SELECT list. Take the old instances out of service before upgrading, or run the
upgrade during a maintenance window. The downgrade restores the column and its
``false`` default, but not per-user grants: the flag authorizes nothing, so any
prior grant is recoverable by granting the storage permission instead.

Revision ID: 202608101500
Revises: 202608101300
Create Date: 2026-08-10 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608101500"
down_revision: str | None = "202608101300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "is_platform_admin")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
