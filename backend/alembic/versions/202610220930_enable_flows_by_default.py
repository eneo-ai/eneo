"""Turn flows on by default and give existing predefined roles their permissions

202610211900 seeded the ``flows_core`` flag off. Flows are now on for every
tenant; the flag stays as a per-tenant off switch (a tenant row with
``enabled = false``).

Roles created before the flow permissions existed never received them, so an
upgraded tenant would see nothing even with the flag on. Predefined Owner roles
get the four flow permissions and predefined AI Configurator roles get
``flows_trace``, as new tenants receive them from ``predefined_roles.yml``.
Custom roles are left to their administrators.

The downgrade turns the flag off again and leaves the permissions: while the
flag is off they grant nothing, and Owner roles of tenants created after the
permissions existed held them before this revision too.

Revision ID: 202610220930
Revises: 202610212300
Create Date: 2026-10-22 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610220930"
down_revision: str | None = "202610212300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANTS = {
    "Owner": ("flows_view", "flows_run", "flows_manage", "flows_trace"),
    "AI Configurator": ("flows_trace",),
}


def upgrade() -> None:
    op.execute(
        "UPDATE global_feature_flags SET enabled = true, updated_at = now() "
        "WHERE name = 'flows_core'"
    )
    for source, permissions in _GRANTS.items():
        for permission in permissions:
            op.get_bind().execute(
                sa.text(
                    "UPDATE roles SET permissions = array_append(permissions, :permission) "
                    "WHERE predefined_source = :source "
                    "AND NOT (:permission = ANY(permissions))"
                ),
                {"permission": permission, "source": source},
            )


def downgrade() -> None:
    op.execute(
        "UPDATE global_feature_flags SET enabled = false, updated_at = now() "
        "WHERE name = 'flows_core'"
    )
