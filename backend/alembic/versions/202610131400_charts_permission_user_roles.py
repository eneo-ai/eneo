"""Grant the charts permission to the predefined User and AI Configurator roles.

The charts capability reached upgraded tenants in two steps: 202610081100
added the purpose with no grant, and 202610091100 granted the permission to
the predefined Owner role only. New tenants get it from the roles template
for User, AI Configurator and Owner, as they do file analysis and file
creation. Upgraded tenants now get the same, so who can use charts no longer
depends on when the tenant was created. Roles administrators made themselves
are left alone.

Revision ID: 202610131400
Revises: 202610091100
Create Date: 2026-10-13 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610131400"
down_revision: str | None = "202610091100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION = "charts"
# Owner was granted by 202610091100 and is not touched here, so a downgrade
# restores exactly that state.
_ROLES = ("User", "AI Configurator")


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
        .where(roles.c.predefined_source.in_(_ROLES))
        .where(sa.not_(roles.c.permissions.any(_PERMISSION)))
        .values(permissions=sa.func.array_append(roles.c.permissions, _PERMISSION))
    )


def downgrade() -> None:
    roles = _roles()
    op.execute(
        roles.update()
        .where(roles.c.predefined_source.in_(_ROLES))
        .values(permissions=sa.func.array_remove(roles.c.permissions, _PERMISSION))
    )
