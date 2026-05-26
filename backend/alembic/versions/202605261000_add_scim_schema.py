"""add scim schema: external_id on users and user_groups, scim_token_hash on tenants

Revision ID: 202605261000
Revises: 202605061100
Create Date: 2026-05-26
"""

from alembic import op

# revision identifiers, used by Alembic
revision = '202605261000'
down_revision = '202605061100'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_external_id ON users (external_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_external_id
        ON users (tenant_id, external_id)
        WHERE external_id IS NOT NULL
    """)
    op.execute("ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS external_id VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_groups_external_id ON user_groups (external_id)")
    op.execute("ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS state VARCHAR")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS scim_token_hash VARCHAR(64)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_scim_token_hash ON tenants (scim_token_hash)")
    # Replace the broad unique constraint with a partial unique index so that
    # soft-deleted groups do not block re-creation of a group with the same name.
    # UNIQUE CONSTRAINT does not support a WHERE clause, hence the switch to an index.
    op.execute(
        "ALTER TABLE user_groups DROP CONSTRAINT IF EXISTS user_groups_name_tenant_unique"
    )
    op.execute("DROP INDEX IF EXISTS user_groups_name_tenant_unique")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS user_groups_name_tenant_unique
        ON user_groups (name, tenant_id)
        WHERE state IS NULL OR state != 'deleted'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS user_groups_name_tenant_unique")
    op.execute("""
        ALTER TABLE user_groups
        ADD CONSTRAINT user_groups_name_tenant_unique UNIQUE (name, tenant_id)
    """)
    op.execute("DROP INDEX IF EXISTS ix_tenants_scim_token_hash")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS scim_token_hash")
    op.execute("ALTER TABLE user_groups DROP COLUMN IF EXISTS state")
    op.execute("DROP INDEX IF EXISTS ix_user_groups_external_id")
    op.execute("ALTER TABLE user_groups DROP COLUMN IF EXISTS external_id")
    op.execute("DROP INDEX IF EXISTS uq_users_tenant_external_id")
    op.execute("DROP INDEX IF EXISTS ix_users_external_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS external_id")
