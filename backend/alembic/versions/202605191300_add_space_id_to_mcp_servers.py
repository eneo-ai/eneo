"""mcp_servers.space_id: scope MCP servers to a space (nullable = tenant-wide)

Today the ``mcp_servers`` catalog is tenant-wide and admin-curated. Space
owners and editors should be able to register their own MCP servers
(including upcoming Ladan collections proxied through eneo) without
involving a tenant admin. We add a nullable ``space_id`` column:

- ``NULL``  -> tenant-wide catalog entry (current behavior, admin-managed)
- ``NOT NULL`` -> space-private entry, only visible inside that space

Uniqueness needs to stay per-namespace: a tenant-wide name should not
collide with another tenant-wide name, and a space-private name should not
collide with another name *in the same space*. Postgres partial unique
indexes express this cleanly.

The original ``uq_mcp_servers_tenant_name`` is dropped because its semantics
(tenant + name uniqueness across both scopes) would prevent a space from
having a private MCP server with the same name as a tenant-wide one.

Revision ID: 202605191300
Revises: 202605181000
Create Date: 2026-05-19
"""

import sqlalchemy as sa

from alembic import op

revision = "202605191300"
down_revision = "202605181000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "space_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mcp_servers_space_id",
        "mcp_servers",
        ["space_id"],
    )

    op.drop_constraint("uq_mcp_servers_tenant_name", "mcp_servers", type_="unique")

    op.create_index(
        "uq_mcp_servers_tenant_name_global",
        "mcp_servers",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("space_id IS NULL"),
    )
    op.create_index(
        "uq_mcp_servers_tenant_space_name",
        "mcp_servers",
        ["tenant_id", "space_id", "name"],
        unique=True,
        postgresql_where=sa.text("space_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_mcp_servers_tenant_space_name", table_name="mcp_servers")
    op.drop_index("uq_mcp_servers_tenant_name_global", table_name="mcp_servers")

    op.create_unique_constraint(
        "uq_mcp_servers_tenant_name", "mcp_servers", ["tenant_id", "name"]
    )

    op.drop_index("ix_mcp_servers_space_id", table_name="mcp_servers")
    op.drop_column("mcp_servers", "space_id")
