"""Add the document_creation and spreadsheet_creation capability purposes

Spaces, assistants and governance policies may now save
``document_creation`` and ``spreadsheet_creation`` as capabilities, governed by
permissions of the same names. Both are granted to the predefined User, AI
Configurator and Owner roles (as with tabular analysis); custom roles are left
unchanged for tenant admins to opt in. The YAML template in
``server/dependencies/predefined_roles.yml`` covers new tenants.

Revision ID: 202609291000
Revises: 202609241000
Create Date: 2026-09-29

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202609291000"
down_revision = "202609241000"
branch_labels = None
depends_on = None

_CONSTRAINTS = (
    ("space_capabilities", "ck_space_capability_purpose"),
    ("assistant_capabilities", "ck_assistant_capability_purpose"),
    ("governance_policy_capabilities", "ck_policy_capability_purpose"),
)
_PREVIOUS = ("web_search", "image_generation", "tabular_analysis")
_ADDED = ("document_creation", "spreadsheet_creation")
_PREDEFINED_ROLES = ("User", "AI Configurator", "Owner")


def _replace_constraints(purposes: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{purpose}'" for purpose in purposes)
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"purpose IN ({allowed})")


def upgrade() -> None:
    _replace_constraints(_PREVIOUS + _ADDED)
    roles = sa.table(
        "roles",
        sa.column("permissions", sa.ARRAY(sa.String())),
        sa.column("predefined_source", sa.String()),
    )
    for permission in _ADDED:
        op.execute(
            roles.update()
            .where(roles.c.predefined_source.in_(_PREDEFINED_ROLES))
            .where(sa.not_(roles.c.permissions.any(permission)))
            .values(permissions=sa.func.array_append(roles.c.permissions, permission))
        )


def downgrade() -> None:
    for purpose in _ADDED:
        for table, _ in _CONSTRAINTS:
            op.execute(f"DELETE FROM {table} WHERE purpose = '{purpose}'")
        # The older code has no such purpose; its providers are re-added after
        # an upgrade. Renaming them to general could collide with a general
        # server's name, so they are removed (tools and links cascade).
        op.execute(f"DELETE FROM mcp_servers WHERE purpose = '{purpose}'")
        op.execute(
            f"UPDATE roles SET permissions = array_remove(permissions, '{purpose}')"
        )
    _replace_constraints(_PREVIOUS)
