"""Add the compute capability purpose

Spaces, assistants and governance policies may now save ``compute`` (exact
calculations in an isolated JavaScript sandbox, with CSV export of tabular
results) as a capability, governed by a permission of the same name. The
permission is granted to the predefined Owner role only, as charts was by
202610091100 and as the YAML template in
``server/dependencies/predefined_roles.yml`` gives new tenants: a function
that runs code or writes files is opted in for other roles by an
administrator. Custom roles are left unchanged.

Existing bundled compute servers with purpose ``general`` are left as they are.
They keep working as ordinary MCP servers next to the new function and are
retired through the admin UI.

Revision ID: 202610131300
Revises: 202610091100
Create Date: 2026-10-13

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610131300"
down_revision = "202610091100"
branch_labels = None
depends_on = None

_CONSTRAINTS = (
    ("space_capabilities", "ck_space_capability_purpose"),
    ("assistant_capabilities", "ck_assistant_capability_purpose"),
    ("governance_policy_capabilities", "ck_policy_capability_purpose"),
)
_PREVIOUS = (
    "web_search",
    "image_generation",
    "file_analysis",
    "file_creation",
    "charts",
)
_ADDED = "compute"
_PREDEFINED_ROLES = ("Owner",)


def _replace_constraints(purposes: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{purpose}'" for purpose in purposes)
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"purpose IN ({allowed})")


def _roles() -> sa.TableClause:
    return sa.table(
        "roles",
        sa.column("permissions", sa.ARRAY(sa.String())),
        sa.column("predefined_source", sa.String()),
    )


def upgrade() -> None:
    _replace_constraints((*_PREVIOUS, _ADDED))
    roles = _roles()
    op.execute(
        roles.update()
        .where(roles.c.predefined_source.in_(_PREDEFINED_ROLES))
        .where(sa.not_(roles.c.permissions.any(_ADDED)))
        .values(permissions=sa.func.array_append(roles.c.permissions, _ADDED))
    )


def downgrade() -> None:
    for table, _ in _CONSTRAINTS:
        op.execute(f"DELETE FROM {table} WHERE purpose = '{_ADDED}'")
    # The older code has no such purpose; its provider is re-added after an
    # upgrade. Renaming it to general could collide with a general server's
    # name, so it is removed (tools and links cascade).
    op.execute(f"DELETE FROM mcp_servers WHERE purpose = '{_ADDED}'")
    op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{_ADDED}')")
    _replace_constraints(_PREVIOUS)
