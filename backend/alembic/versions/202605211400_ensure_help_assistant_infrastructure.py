"""Ensure per-tenant Help Assistant infrastructure (org-space + system user)

Help Assistants are not preseeded — an admin installs them from the admin UI
(``OrgSpaceAssistantRoleService.install_helper``), which creates the assistant
on demand. But two pieces of per-tenant *plumbing* must exist for that install
to have somewhere to live and someone to own it:

  1. An org-space (``spaces`` row with ``user_id IS NULL`` AND
     ``tenant_space_id IS NULL``) — the admin-only space Help Assistants live
     in. Named to match ``SpaceService.TENANT_SPACE_NAME`` so the runtime
     ``get_or_create_tenant_space()`` resolves the *same* space by name instead
     of creating a duplicate.
  2. A per-tenant system user (``users.is_system_user = true``) — the owner of
     Help Assistants (they cannot belong to a real person who might be deleted,
     or would otherwise see them in their own lists).

Idempotence:
  - Each insert uses ``WHERE NOT EXISTS``; re-running ``upgrade()`` after a
    successful run leaves the database unchanged.

Downgrade:
  - No-op. These rows may be referenced by helpers an admin has since
    installed; auto-deleting them on rollback would orphan that work.

PRD §2, §8.

Revision ID: 202605211400
Revises: 202605211300
Create Date: 2026-05-21
"""

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic
revision = "202605211400"
down_revision = "202605211300"
branch_labels = None
depends_on = None


# Must match ``SpaceService.TENANT_SPACE_NAME`` so the runtime
# ``get_or_create_tenant_space()`` resolves this space by name rather than
# creating a second org-space per tenant.
ORG_SPACE_NAME = "Organization space"


def upgrade() -> None:
    conn = op.get_bind()

    # Phase 1 — ensure an org-space per tenant. The partial unique index
    # `idx_unique_org_space_per_tenant` already enforces at most one org-space
    # per tenant; the NOT EXISTS guard keeps the insert idempotent without
    # relying on ON CONFLICT against a partial index.
    conn.execute(
        text(
            """
            INSERT INTO spaces (
                id, tenant_id, user_id, tenant_space_id, name, description,
                created_at, updated_at
            )
            SELECT gen_random_uuid(), t.id, NULL, NULL, :name, NULL, now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM spaces s
                WHERE s.tenant_id = t.id
                  AND s.user_id IS NULL
                  AND s.tenant_space_id IS NULL
            )
            """
        ),
        {"name": ORG_SPACE_NAME},
    )

    # Phase 2 — ensure a per-tenant system user. Email and username are
    # synthesized from the tenant id so re-runs are stable and the active-
    # email partial-unique index (`idx_unique_active_user_email`) never fires.
    # `password` and `salt` are NULL — the password verifier cannot produce a
    # match for NULL, and `state = 'inactive'` plus `is_active = false` keep
    # the user out of every login/search path.
    conn.execute(
        text(
            """
            INSERT INTO users (
                id, email, username, email_verified, salt, password,
                is_active, state, used_tokens, tenant_id, quota_limit,
                is_system_user, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                'system+' || t.id::text || '@eneo.local',
                'system+' || t.id::text,
                false,
                NULL,
                NULL,
                false,
                'inactive',
                0,
                t.id,
                NULL,
                true,
                now(),
                now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM users u
                WHERE u.tenant_id = t.id AND u.is_system_user = true
            )
            """
        )
    )


def downgrade() -> None:
    # Intentional no-op. See module docstring for rationale.
    pass
