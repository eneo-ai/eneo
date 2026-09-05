"""Persist capability intent independently of provider rows.

Revision ID: 202609041000
Revises: 202607101007
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609041000"
down_revision = "202607101007"
branch_labels = None
depends_on = None

OWNERS = (
    ("space_capabilities", "space_id", "spaces", "spaces_mcp_servers"),
    ("assistant_capabilities", "assistant_id", "assistants", "assistant_mcp_servers"),
    (
        "governance_policy_capabilities",
        "policy_id",
        "governance_policies",
        "governance_policy_mcp_servers",
    ),
)


def upgrade():
    connection = op.get_bind()
    servers = sa.table("mcp_servers", sa.column("id"), sa.column("purpose"))
    tools = sa.table("mcp_server_tools", sa.column("id"), sa.column("mcp_server_id"))
    capability_ids = sa.select(servers.c.id).where(
        servers.c.purpose.in_(("web_search", "image_generation"))
    )
    tool_ids = sa.select(tools.c.id).where(tools.c.mcp_server_id.in_(capability_ids))
    for name, owner, parent, legacy_name in OWNERS:
        columns = [
            sa.Column(
                owner,
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(parent + ".id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("purpose", sa.String(), primary_key=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "purpose IN ('web_search', 'image_generation')",
                name={
                    "space_capabilities": "ck_space_capability_purpose",
                    "assistant_capabilities": "ck_assistant_capability_purpose",
                    "governance_policy_capabilities": "ck_policy_capability_purpose",
                }[name],
            ),
        ]
        policy = name == "governance_policy_capabilities"
        if policy:
            columns.append(
                sa.Column(
                    "is_default_enabled",
                    sa.Boolean(),
                    server_default=sa.true(),
                    nullable=False,
                )
            )
        op.create_table(name, *columns)
        legacy = sa.table(
            legacy_name,
            sa.column(owner),
            sa.column("mcp_server_id"),
            sa.column("is_default_enabled"),
        )
        target = sa.table(
            name,
            sa.column(owner),
            sa.column("purpose"),
            sa.column("is_default_enabled"),
        )
        values = [legacy.c[owner], servers.c.purpose]
        names = [owner, "purpose"]
        if policy:
            values.append(sa.func.bool_or(legacy.c.is_default_enabled))
            names.append("is_default_enabled")
        selection = (
            sa.select(*values)
            .select_from(legacy.join(servers, servers.c.id == legacy.c.mcp_server_id))
            .where(servers.c.id.in_(capability_ids))
            .group_by(legacy.c[owner], servers.c.purpose)
        )
        connection.execute(sa.insert(target).from_select(names, selection))
        connection.execute(
            sa.delete(legacy).where(legacy.c.mcp_server_id.in_(capability_ids))
        )
    for name, column in (
        ("spaces_mcp_server_tools", "mcp_server_tool_id"),
        ("assistant_mcp_server_tools", "mcp_server_tool_id"),
        ("governance_policy_disabled_mcp_tools", "mcp_tool_id"),
    ):
        table = sa.table(name, sa.column(column))
        connection.execute(sa.delete(table).where(table.c[column].in_(tool_ids)))


def downgrade():
    # A purpose may now have no provider at all, so restoring FK markers
    # would silently discard saved intent. Require an explicit data restore.
    raise RuntimeError(
        "Independent capability settings cannot be represented by provider markers; restore a pre-upgrade backup to downgrade."
    )
