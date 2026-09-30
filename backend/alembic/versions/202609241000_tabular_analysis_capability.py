"""Add the tabular_analysis capability purpose

Spaces, assistants and governance policies may now save ``tabular_analysis``
as a capability, and the ``tabular_analysis`` permission governs its use. It
is granted to the predefined User, AI Configurator and Owner roles (matching
web search and image generation). Custom roles are left unchanged: running
analysis over attachments is a new capability, so tenant admins opt their own
roles in. The YAML template in ``server/dependencies/predefined_roles.yml``
covers new tenants.

Revision ID: 202609241000
Revises: 202609291000
Create Date: 2026-09-24

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202609241000"
down_revision = "202609291000"
branch_labels = None
depends_on = None

_CONSTRAINTS = (
    ("space_capabilities", "ck_space_capability_purpose"),
    ("assistant_capabilities", "ck_assistant_capability_purpose"),
    ("governance_policy_capabilities", "ck_policy_capability_purpose"),
)
_PREDEFINED_ROLES = ("User", "AI Configurator", "Owner")


def _replace_constraints(purposes: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{purpose}'" for purpose in purposes)
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"purpose IN ({allowed})")


def upgrade() -> None:
    _replace_constraints(("web_search", "image_generation", "tabular_analysis"))
    roles = sa.table(
        "roles",
        sa.column("permissions", sa.ARRAY(sa.String())),
        sa.column("predefined_source", sa.String()),
    )
    op.execute(
        roles.update()
        .where(roles.c.predefined_source.in_(_PREDEFINED_ROLES))
        .where(sa.not_(roles.c.permissions.any("tabular_analysis")))
        .values(
            permissions=sa.func.array_append(roles.c.permissions, "tabular_analysis")
        )
    )


def downgrade() -> None:
    for table, _ in _CONSTRAINTS:
        op.execute(f"DELETE FROM {table} WHERE purpose = 'tabular_analysis'")
    # The older code has no such purpose; its providers are re-added after an
    # upgrade. Renaming them to general could collide with a general server's
    # name, so they are removed (tools and links cascade).
    op.execute("DELETE FROM mcp_servers WHERE purpose = 'tabular_analysis'")
    _replace_constraints(("web_search", "image_generation"))
    op.execute(
        "UPDATE roles SET permissions = array_remove(permissions, 'tabular_analysis')"
    )
