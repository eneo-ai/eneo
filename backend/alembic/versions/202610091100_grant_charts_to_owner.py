"""Grant the charts permission to the predefined Owner role.

The charts capability shipped with a permission of its own but no grant, so
on upgraded tenants not even owners could use the chart tools their policy
enabled. The predefined Owner role now gets it, as new tenants' owners do
from the YAML template. Other roles are left to administrators.

Revision ID: 202610091100
Revises: 202610091000
Create Date: 2026-10-09 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610091100"
down_revision: str | None = "202610091000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION = "charts"
_ROLE = "Owner"


def _roles() -> sa.TableClause:
    return sa.table(
        "roles",
        sa.column("permissions", sa.ARRAY(sa.String())),
        sa.column("predefined_source", sa.String()),
    )


def upgrade() -> None:
    roles = _roles()
    op.execute(
        roles.update()
        .where(roles.c.predefined_source == _ROLE)
        .where(sa.not_(roles.c.permissions.any(_PERMISSION)))
        .values(permissions=sa.func.array_append(roles.c.permissions, _PERMISSION))
    )


def downgrade() -> None:
    roles = _roles()
    op.execute(
        roles.update()
        .where(roles.c.predefined_source == _ROLE)
        .values(permissions=sa.func.array_remove(roles.c.permissions, _PERMISSION))
    )
