"""Unify roles system: merge predefined roles into tenant-scoped roles

Revision ID: unify_roles
Revises: 20260319_add_nickname
Create Date: 2026-03-24
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "unify_roles"
down_revision = "20260319_add_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add predefined_source column to roles table
    op.add_column(
        "roles",
        sa.Column("predefined_source", sa.String(), nullable=True),
    )

    # 2. Seed tenant-scoped roles from predefined templates
    # For each tenant × predefined role, create a custom role (skip if name already exists)
    op.execute(
        """
        INSERT INTO roles (id, name, permissions, tenant_id, predefined_source, created_at, updated_at)
        SELECT gen_random_uuid(), pr.name, pr.permissions, t.id, pr.name, now(), now()
        FROM predefined_roles pr CROSS JOIN tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.name = pr.name
        );
        """
    )

    # For existing custom roles with matching names, set predefined_source
    op.execute(
        """
        UPDATE roles r SET predefined_source = pr.name
        FROM predefined_roles pr
        WHERE r.name = pr.name AND r.predefined_source IS NULL;
        """
    )

    # 3. Migrate user-role assignments from predefined to custom roles
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
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("permissions", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Recreate junction table
    op.create_table(
        "users_predefined_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("predefined_role_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["predefined_role_id"], ["predefined_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "predefined_role_id"),
    )

    # Recreate predefined roles from roles with predefined_source
    op.execute(
        """
        INSERT INTO predefined_roles (id, name, permissions, created_at, updated_at)
        SELECT DISTINCT ON (predefined_source)
            gen_random_uuid(), predefined_source, permissions, created_at, updated_at
        FROM roles
        WHERE predefined_source IS NOT NULL;
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
