"""Auto seed allowed_origins with PUBLIC_ORIGIN

Revision ID: auto_seed_allowed_origins
Revises: 3914e3c83f18
Create Date: 2025-10-20 17:30:00.000000
"""

import logging
import os
from typing import Optional

from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = "auto_seed_allowed_origins"
down_revision = "3914e3c83f18"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.env")


def _resolve_origin() -> Optional[str]:
    candidates = [
        os.getenv("PUBLIC_ORIGIN"),
        os.getenv("ORIGIN"),
        os.getenv("INTRIC_BACKEND_URL"),
    ]

    for candidate in candidates:
        if not candidate:
            continue

        origin = candidate.strip().rstrip("/")
        if not origin:
            continue

        if origin.startswith("http://") or origin.startswith("https://"):
            return origin

    return None


def upgrade() -> None:
    origin = _resolve_origin()

    if origin is None:
        logger.warning(
            "[allowed_origins] Skipping backfill – PUBLIC_ORIGIN/ORIGIN/INTRIC_BACKEND_URL "
            "not set in environment."
        )
        return

    conn = op.get_bind()

    default_tenant_name = os.getenv("DEFAULT_TENANT_NAME")

    tenant = None

    if default_tenant_name:
        tenant = conn.execute(
            text("SELECT id, name FROM tenants WHERE name = :name"),
            {"name": default_tenant_name},
        ).fetchone()

    if tenant is None:
        tenant = conn.execute(
            text("SELECT id, name FROM tenants ORDER BY name ASC LIMIT 1")
        ).fetchone()

    if tenant is None:
        logger.info("[allowed_origins] No tenants found; nothing to backfill.")
        return

    tenant_id, tenant_name = tenant

    existing = conn.execute(
        text("SELECT tenant_id FROM allowed_origins WHERE url = :url"),
        {"url": origin},
    ).fetchone()

    if existing:
        logger.info(
            "[allowed_origins] Origin '%s' already registered for tenant id %s; "
            "no changes made.",
            origin,
            existing[0],
        )
        return

    conn.execute(
        text(
            """
            INSERT INTO allowed_origins (url, tenant_id)
            VALUES (:url, :tenant_id)
            ON CONFLICT (url) DO NOTHING
            """
        ),
        {"url": origin, "tenant_id": tenant_id},
    )

    logger.info(
        "[allowed_origins] Seeded origin '%s' for tenant '%s'.",
        origin,
        tenant_name,
    )


def downgrade() -> None:
    # No data removal on downgrade to avoid deleting legitimate tenant configuration.
    pass
