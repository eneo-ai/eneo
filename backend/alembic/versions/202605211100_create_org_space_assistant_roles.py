"""create org_space_assistant_roles

Records which assistant fills which platform role (e.g. ``prompt_guide``)
inside an organization space. UNIQUE(org_space_id, kind) keeps each role
slot single-occupancy per org-space. Tenant scoping derives from
``spaces.tenant_id`` via ``org_space_id``; no separate ``tenant_id`` column
per PRD §1.

Entities, repos, services, and routers land in later steps. This migration
is schema-only.

Revision ID: 202605211100
Revises: 202605211000
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605211100"
down_revision = "202605211000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_space_assistant_roles",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_space_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_visible_to_users",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["org_space_id"], ["spaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_space_id", "kind", name="uq_org_space_roles_kind"
        ),
    )
    op.create_index(
        op.f("ix_org_space_assistant_roles_kind"),
        "org_space_assistant_roles",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_org_space_assistant_roles_org_space_id"),
        "org_space_assistant_roles",
        ["org_space_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_org_space_assistant_roles_org_space_id"),
        table_name="org_space_assistant_roles",
    )
    op.drop_index(
        op.f("ix_org_space_assistant_roles_kind"),
        table_name="org_space_assistant_roles",
    )
    op.drop_table("org_space_assistant_roles")
