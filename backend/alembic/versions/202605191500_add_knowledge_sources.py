"""knowledge_sources: ownership map for proxied Ladan collections

Eneo proxies its users' "New knowledge source" actions through a single
shared Ladan instance (single-tenant upstream, multi-tenant caller).
Tenant and space isolation are enforced on the eneo side via this
ownership table — every row maps an upstream Ladan slug to the owning
(tenant_id, space_id, owner_user_id, mcp_server_id) tuple.

The matching MCP server row in eneo's own ``mcp_servers`` table is what
assistants actually pick up (via Phase 1's space-scoped MCP visibility).
Deleting an ownership row cascades through the FK to the MCP server row
(``ON DELETE CASCADE``) and the upstream Ladan collection is deleted by
the service layer in the same flow.

Revision ID: 202605191500
Revises: 202605191300
Create Date: 2026-05-19
"""

import sqlalchemy as sa

from alembic import op

revision = "202605191500"
down_revision = "202605191300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ladan_slug", sa.Text(), nullable=False),
        sa.Column(
            "mcp_server_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_knowledge_sources_tenant_space",
        "knowledge_sources",
        ["tenant_id", "space_id"],
    )
    op.create_unique_constraint(
        "uq_knowledge_sources_tenant_slug",
        "knowledge_sources",
        ["tenant_id", "ladan_slug"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_knowledge_sources_tenant_slug", "knowledge_sources", type_="unique"
    )
    op.drop_index("ix_knowledge_sources_tenant_space", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
