"""Unify roles system: merge predefined roles into tenant-scoped roles

Revision ID: unify_roles
Revises: 202604101000
Create Date: 2026-03-24

Notes on backward compatibility and edge cases handled by this migration:

- Preflight (step 0) halts on case-INSENSITIVE name collisions between
  existing custom roles and the Owner/User/AI Configurator templates, so
  `"User"` and `"user"` both trip the check.
- Preflight (step 0b) halts on orphaned users_predefined_roles FK rows so
  we don't silently drop user→role assignments during step 3.
- Step 2 is idempotent via `ON CONFLICT DO NOTHING` — safe to re-run after
  a mid-migration crash once the operator has resolved the underlying
  issue.
- Step 7 back-compat grants `shared_spaces` to every existing role so no
  user regresses from this migration. This is SHARED_SPACES-specific
  because shared spaces are a core Eneo feature and the customer-requested
  opt-out model is: admins REMOVE the permission from roles they want to
  restrict. Future permission additions (e.g. splitting ADMIN into sub-
  permissions) MUST populate seeded roles thoughtfully — do NOT blanket-
  grant to every custom role, as that silently elevates restricted roles.
- Step 7 uses `COALESCE(permissions, ARRAY[]::text[])` for NULL-safety;
  step 8 tightens the column to NOT NULL so the NULL branch can never
  arise again.
- Downgrade is LOSSY: DISTINCT ON picks the most-recently-updated
  permissions per template, so tenant-specific customizations do not
  survive a down-up round-trip, and custom roles created after upgrade
  are orphaned.
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
    #
    # Compare case-insensitively: Postgres `name = name` is case-sensitive,
    # but "user" vs "User" are the same role to an operator and silently
    # coexisting post-migration confuses administration.
    bind = op.get_bind()
    collisions = bind.execute(
        sa.text(
            """
            SELECT r.tenant_id, r.id, r.name
            FROM roles r
            JOIN predefined_roles pr ON LOWER(pr.name) = LOWER(r.name)
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
            "predefined template names (Owner / User / AI Configurator), "
            "case-insensitive. Resolve and re-run.\n\n"
            f"{details}\n\n"
            "For each row, rename the custom role to avoid the collision:\n"
            "  UPDATE roles SET name = name || ' (legacy)' WHERE id = '<role_id>';\n"
            "or delete it if unused:\n"
            "  DELETE FROM roles WHERE id = '<role_id>';\n\n"
            "NOTE: after renaming, the legacy role is no longer eligible to "
            "become this tenant's default_role_id — the freshly-seeded "
            "template-sourced 'User' role will be assigned instead. Any "
            "custom permissions on the legacy role must be re-granted via "
            "direct assignment to users who need them."
        )

    # 0b. Preflight: detect orphaned users_predefined_roles rows whose
    # predefined_role_id no longer matches a predefined_roles row. Step 3's
    # INNER JOIN would silently drop them, leaving the affected users
    # role-less post-migration. Halt so the operator can resolve.
    orphans = bind.execute(
        sa.text(
            """
            SELECT upr.user_id, upr.predefined_role_id
            FROM users_predefined_roles upr
            LEFT JOIN predefined_roles pr ON pr.id = upr.predefined_role_id
            WHERE pr.id IS NULL
            """
        )
    ).fetchall()

    if orphans:
        details = "\n".join(
            f"  user_id={row.user_id} predefined_role_id={row.predefined_role_id}"
            for row in orphans
        )
        raise RuntimeError(
            "unify_roles migration halted: users_predefined_roles has "
            "orphaned rows whose predefined_role_id no longer exists. "
            "These would be silently dropped by step 3 — leaving users "
            "without a role. Resolve and re-run:\n\n"
            f"{details}\n\n"
            "DELETE the orphans once you confirm they are safe to drop:\n"
            "  DELETE FROM users_predefined_roles\n"
            "  WHERE predefined_role_id NOT IN (SELECT id FROM predefined_roles);"
        )

    # 1. Add predefined_source column to roles table
    op.add_column(
        "roles",
        sa.Column("predefined_source", sa.String(), nullable=True),
    )

    # 2. Seed tenant-scoped roles from predefined templates.
    # Preflight guarantees no name collisions, but we still use
    # ON CONFLICT DO NOTHING so the migration is idempotent: if step 3 or
    # later crashes and the operator re-runs upgrade after fixing the
    # underlying cause, step 2 does not raise UniqueViolation on the
    # `roles_name_tenant_unique` constraint.
    op.execute(
        """
        INSERT INTO roles (id, name, permissions, tenant_id, predefined_source, created_at, updated_at)
        SELECT gen_random_uuid(), pr.name, pr.permissions, t.id, pr.name, now(), now()
        FROM predefined_roles pr CROSS JOIN tenants t
        ON CONFLICT ON CONSTRAINT roles_name_tenant_unique DO NOTHING;
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

    # 7. Back-compat: grant `shared_spaces` to every existing role so no
    #    user loses the ability to create shared spaces from this migration.
    #    Admins OPT OUT by removing the permission from roles they want to
    #    restrict. This blanket grant is SHARED_SPACES-specific; see module
    #    docstring for why it's the wrong pattern for other permissions.
    #
    #    NULL-safe via COALESCE: the pre-migration schema did not explicitly
    #    forbid NULL permissions arrays. `array_append(NULL, x)` returns NULL
    #    and `x = ANY(NULL)` is NULL/UNKNOWN, so without COALESCE a NULL row
    #    would be skipped on both branches and retain NULL.
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(COALESCE(permissions, ARRAY[]::text[]), 'shared_spaces')
        WHERE NOT ('shared_spaces' = ANY(COALESCE(permissions, ARRAY[]::text[])));
        """
    )

    # 8. Tighten the column: after step 7, no role has NULL permissions.
    # Prevent the NULL branch from re-emerging via direct SQL inserts.
    op.alter_column("roles", "permissions", nullable=False)


def downgrade() -> None:
    # Loosen the NOT NULL constraint first so downgrade doesn't block on
    # any row that might be inserted NULL between upgrade and downgrade.
    op.alter_column("roles", "permissions", nullable=True)

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

    # Recreate predefined roles from roles with predefined_source.
    # LOSSY: `DISTINCT ON (predefined_source) ORDER BY updated_at DESC`
    # picks whichever tenant's copy of a template was edited most recently
    # and uses THOSE permissions as the global template — silently
    # propagating one tenant's customization to every tenant on re-upgrade.
    # Custom roles (predefined_source IS NULL) are dropped. Accept as
    # known-lossy; do not rely on up→down→up to be a no-op.
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
