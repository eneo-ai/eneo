"""Backfill resource_permissions for sk_ keys

For sk_ keys where resource_permissions is NULL, populate all four
resource types with the key's current permission value. This makes
the fine-grained model the single source of truth for sk_ keys.
pk_ keys are left unchanged (they do not support fine-grained permissions).

Revision ID: 202604101000
Revises: 202604091000
Create Date: 2026-04-10
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202604101000"
down_revision = "202604091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE api_keys_v2
        SET resource_permissions = jsonb_build_object(
            'assistants', permission,
            'apps', permission,
            'spaces', permission,
            'knowledge', permission
        )
        WHERE resource_permissions IS NULL
          AND key_type = 'sk_';
    """)


def downgrade() -> None:
    # Setting resource_permissions back to NULL for sk_ keys that were
    # backfilled. We can only reverse keys whose four resource types are
    # all identical (i.e. were created by the backfill, not manually set).
    op.execute("""
        UPDATE api_keys_v2
        SET resource_permissions = NULL
        WHERE key_type = 'sk_'
          AND resource_permissions IS NOT NULL
          AND resource_permissions->>'assistants' = permission
          AND resource_permissions->>'apps' = permission
          AND resource_permissions->>'spaces' = permission
          AND resource_permissions->>'knowledge' = permission;
    """)
