"""Give organization admin keys the administration permission

The organization's administration (users, roles, settings) used to open for
any organization-scoped secret key whose highest resource permission was
admin. It now takes a permission of its own, ``administration``, stored with
the resource permissions. Every key that reached the administration before
gets it at admin, so no integration stops working; a key made after this only
has it when someone gives it.

Keys without per-resource permissions are left alone: for them the old rule
still holds (see ``administration_level`` in ``auth_models``).

Revision ID: 202611271100
Revises: 202611201305
Create Date: 2026-11-27
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202611271100"
down_revision = "202611201305"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE api_keys_v2
        SET resource_permissions =
            resource_permissions || jsonb_build_object('administration', 'admin')
        WHERE key_type = 'sk_'
          AND scope_type = 'tenant'
          AND permission = 'admin'
          AND resource_permissions IS NOT NULL
          AND NOT jsonb_exists(resource_permissions, 'administration');
    """)


def downgrade() -> None:
    # The earlier code refuses a key whose permissions name something it does
    # not know, so the permission is taken off every key, given here or later.
    op.execute("""
        UPDATE api_keys_v2
        SET resource_permissions = resource_permissions - 'administration'
        WHERE jsonb_exists(resource_permissions, 'administration');
    """)
