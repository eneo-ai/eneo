"""Backfill tenant_space_id and create org hubs
Revision ID: 8cf9fcbc40fb
Revises: 5da161e2e38b
Create Date: 2025-08-15 13:13:48.966663
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic
revision = '8cf9fcbc40fb'
down_revision = '5da161e2e38b'
branch_labels = None
depends_on = None

HUB_NAME = "Organization space"
HUB_DESC = "Delad knowledge för hela tenant"


def upgrade() -> None:
    conn = op.get_bind()

    tenants = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()

    for (tenant_id,) in tenants:
        row = conn.execute(
            sa.text(
                """
                SELECT id
                FROM spaces
                WHERE tenant_id = :tenant_id
                  AND user_id IS NULL
                  AND tenant_space_id IS NULL
                  AND name = :hub_name
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "hub_name": HUB_NAME},
        ).fetchone()

        if row:
            hub_id = row[0]
        else:
            hub_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            conn.execute(
                sa.text(
                    """
                    INSERT INTO spaces (id, name, description, tenant_id, user_id, created_at, updated_at)
                    VALUES (:id, :name, :desc, :tenant_id, NULL, :now, :now)
                    """
                ),
                {
                    "id": hub_id,
                    "name": HUB_NAME,
                    "desc": HUB_DESC,
                    "tenant_id": str(tenant_id),
                    "now": now,
                },
            )

        conn.execute(
            sa.text(
                """
                UPDATE spaces
                SET tenant_space_id = :hub_id
                WHERE tenant_id = :tenant_id
                  AND tenant_space_id IS NULL
                  AND id <> :hub_id
                """
            ),
            {"tenant_id": str(tenant_id), "hub_id": hub_id},
        )


def downgrade() -> None:
 
    conn = op.get_bind()

    #  - Nollställ tenant_space_id överallt (bevarar hubbarna).
    #  - (Vi tar INTE bort hubbar eftersom vi inte kan säkert avgöra vilka
    #    som funnits innan migrationen.)
    conn.execute(sa.text("UPDATE spaces SET tenant_space_id = NULL"))