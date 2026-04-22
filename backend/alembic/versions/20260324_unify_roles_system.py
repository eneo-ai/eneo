"""Unify roles system: merge predefined roles into tenant-scoped roles

Revision ID: unify_roles
Revises: 202604101000
Create Date: 2026-03-24
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "unify_roles"
down_revision = "202604101000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. Preflight: detect name collisions between existing tenant-scoped
    # `roles` and the global `predefined_roles` templates. Auto-taking-over
    # a custom role with a template name would silently overwrite the
    # operator's configured permissions (and, for "User", silently promote
    # the custom role to the tenant's default_role_id). Halt with a clear
    # resolution path instead — migration is wrapped in a transaction, so
    # no DDL has been applied and the operator can resolve and re-run.
    bind = op.get_bind()
    collisions = bind.execute(
        sa.text(
            """
            SELECT r.tenant_id, r.id, r.name
            FROM roles r
            JOIN predefined_roles pr ON pr.name = r.name
            ORDER BY r.tenant_id, r.name
            """
        )
    ).fetchall()

    if collisions:
        details = "\n".join(
            f"  tenant_id={row.tenant_id} role_id={row.id} name='{row.name}'"
            for row in collisions
        )
        raise RuntimeError(
            "unify_roles migration halted: existing custom roles collide with "
            "predefined template names "
            "(Owner / User / AI Configurator). Resolve and re-run:\n\n"
            f"{details}\n\n"
            "For each row, rename the custom role to avoid the collision:\n"
            "  UPDATE roles SET name = name || ' (legacy)' WHERE id = '<role_id>';\n"
            "or delete it if unused:\n"
            "  DELETE FROM roles WHERE id = '<role_id>';"
        )

    # 1. Add predefined_source column to roles table
    op.add_column(
        "roles",
        sa.Column("predefined_source", sa.String(), nullable=True),
    )

    # 2. Seed tenant-scoped roles from predefined templates.
    # Preflight above guarantees no name collisions, so every template
    # row is safe to insert unconditionally.
    op.execute(
        """
        INSERT INTO roles (id, name, permissions, tenant_id, predefined_source, created_at, updated_at)
        SELECT gen_random_uuid(), pr.name, pr.permissions, t.id, pr.name, now(), now()
        FROM predefined_roles pr CROSS JOIN tenants t;
        """
    )

    # 3. Migrate user-role assignments from predefined to tenant-scoped roles
    op.execute(
        """
        INSERT INTO users_roles (user_id, role_id)
        SELECT upr.user_id, r.id
        FROM users_predefined_roles upr
        JOIN users u ON u.id = upr.user_id
        JOIN predefined_roles pr ON pr.id = upr.predefined_role_id
        JOIN roles r ON r.tenant_id = u.tenant_id AND r.predefined_source = pr.name
        ON CONFLICT (user_id, role_id) DO NOTHING;
        """
    )

    # 4. Drop old tables
    op.drop_table("users_predefined_roles")
    op.drop_table("predefined_roles")

    # 5. Add default_role_id to tenants (FK to roles, SET NULL on delete)
    op.add_column(
        "tenants",
        sa.Column("default_role_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_default_role_id",
        "tenants",
        "roles",
        ["default_role_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 6. Set default_role_id to the "User" role for each tenant
    op.execute(
        """
        UPDATE tenants t
        SET default_role_id = r.id
        FROM roles r
        WHERE r.tenant_id = t.id AND r.predefined_source = 'User';
        """
    )

    # 7. Add 'spaces' permission to ALL existing roles (preserves current behavior
    #    where all users can create spaces — now gated by explicit permission)
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'shared_spaces')
        WHERE NOT ('shared_spaces' = ANY(permissions));
        """
    )


def downgrade() -> None:
    # Recreate predefined_roles table
    op.create_table(
        "predefined_roles",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("permissions", sa.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Recreate junction table
    op.create_table(
        "users_predefined_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("predefined_role_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["predefined_role_id"], ["predefined_roles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "predefined_role_id"),
    )

    # Recreate predefined roles from roles with predefined_source
    op.execute(
        """
        INSERT INTO predefined_roles (id, name, permissions, created_at, updated_at)
        SELECT DISTINCT ON (predefined_source)
            gen_random_uuid(), predefined_source, permissions, created_at, updated_at
        FROM roles
        WHERE predefined_source IS NOT NULL
        ORDER BY predefined_source, updated_at DESC;
        """
    )

    # Recreate user assignments
    op.execute(
        """
        INSERT INTO users_predefined_roles (user_id, predefined_role_id)
        SELECT ur.user_id, pr.id
        FROM users_roles ur
        JOIN roles r ON r.id = ur.role_id
        JOIN predefined_roles pr ON pr.name = r.predefined_source
        WHERE r.predefined_source IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )

    # Drop default_role_id from tenants
    op.drop_constraint("fk_tenants_default_role_id", "tenants", type_="foreignkey")
    op.drop_column("tenants", "default_role_id")

    # Drop predefined_source column
    op.drop_column("roles", "predefined_source")
