"""Use File storage policy for file and audio sizes in every Flow.

Revision ID: 202610081100
Revises: 202610081000
"""

import logging

import sqlalchemy as sa

from alembic import op

revision = "202610081100"
down_revision = "202610081000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    result = op.get_bind().execute(
        sa.text("""
        WITH previous AS (
            SELECT id, flow_settings->'input_limits' AS limits
            FROM tenants
            WHERE jsonb_typeof(flow_settings->'input_limits') = 'object'
              AND (flow_settings->'input_limits') ?| ARRAY['file_max_size_bytes', 'audio_max_size_bytes']
        )
        UPDATE tenants AS tenant
        SET flow_settings = jsonb_set(
            tenant.flow_settings, '{input_limits}',
            (tenant.flow_settings->'input_limits') - 'file_max_size_bytes' - 'audio_max_size_bytes'
        )
        FROM previous
        WHERE tenant.id = previous.id
        RETURNING tenant.id, previous.limits->'file_max_size_bytes' AS file_bytes,
                  previous.limits->'audio_max_size_bytes' AS audio_bytes
    """)
    )
    logger = logging.getLogger("alembic.runtime.migration")
    count = 0
    for row in result:
        count += 1
        logger.info(
            "Retired Flow size overrides: tenant=%s file_bytes=%s audio_bytes=%s; File storage now applies",
            row.id,
            row.file_bytes,
            row.audio_bytes,
        )
    logger.info("Retired Flow size overrides for %s tenants", count)


def downgrade() -> None:
    # Do not reinstate retired policy or change existing files on rollback.
    pass
