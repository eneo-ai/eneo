"""grant the storage permission to existing administrator roles

Storage administration moves from the deployment-wide platform flag to a
normal permission. Existing roles predate it, so grant it wherever the
administrator permission already is; new tenants receive it from the
predefined-role seed instead.

Revision ID: 202608061600
Revises: 202608061200
Create Date: 2026-08-06 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608061600"
down_revision: str | None = "202608061200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_append(permissions, 'storage') "
            "WHERE 'admin' = ANY(permissions) "
            "AND NOT ('storage' = ANY(permissions))"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_remove(permissions, 'storage')"
        )
    )
