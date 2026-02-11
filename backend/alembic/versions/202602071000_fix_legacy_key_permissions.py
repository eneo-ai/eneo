"""fix legacy key permissions: user keys WRITE->ADMIN, assistant keys WRITE->READ

Revision ID: 202602071000
Revises: 202602061000
Create Date: 2026-02-07 10:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "202602071000"
down_revision = "202602061000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User keys migrated from legacy: upgrade WRITE -> ADMIN
    # No name match — names are user-editable via PATCH /api-keys/{id}.
    # Discriminators: scope_type (immutable), key_prefix (immutable), hash_version (immutable).
    op.execute("""
        UPDATE api_keys_v2
        SET permission = 'admin'
        WHERE permission = 'write'
          AND scope_type = 'tenant'
          AND key_prefix IN ('inp_', 'ina_')
          AND hash_version IN ('sha256', 'hmac_sha256')
    """)
    # Assistant keys migrated from legacy: downgrade WRITE -> READ
    op.execute("""
        UPDATE api_keys_v2
        SET permission = 'read'
        WHERE permission = 'write'
          AND scope_type = 'assistant'
          AND key_prefix IN ('inp_', 'ina_')
          AND hash_version IN ('sha256', 'hmac_sha256')
    """)


def downgrade() -> None:
    # Reverse user keys: ADMIN -> WRITE (tenant-scoped legacy keys)
    op.execute("""
        UPDATE api_keys_v2
        SET permission = 'write'
        WHERE permission = 'admin'
          AND scope_type = 'tenant'
          AND key_prefix IN ('inp_', 'ina_')
          AND hash_version IN ('sha256', 'hmac_sha256')
    """)
    # Reverse assistant keys: READ -> WRITE (assistant-scoped legacy keys)
    op.execute("""
        UPDATE api_keys_v2
        SET permission = 'write'
        WHERE permission = 'read'
          AND scope_type = 'assistant'
          AND key_prefix IN ('inp_', 'ina_')
          AND hash_version IN ('sha256', 'hmac_sha256')
    """)
