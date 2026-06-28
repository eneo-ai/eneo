"""Backfill allowed_origins from PUBLIC_ORIGIN (2.0.x CORS regression fix)

2.0.0 changed CORS from effectively allow-all (``allow_origins=["*"]``) to a
strict DB-backed allowlist (``allow_origins=[]``). An origin is now accepted
only if it is localhost or matches a row in ``allowed_origins``. Fresh installs
start with an empty table, so the backend omits ``Access-Control-Allow-Origin``
and the SPA cannot reach the API.

The originally intended auto-seed of ``PUBLIC_ORIGIN`` was built and then dropped
before 2.0.0 shipped, leaving only a (false) doc comment. This migration restores
it: register the configured ``PUBLIC_ORIGIN`` for the default/first tenant so
upgraded and fresh single-tenant installs work without manual SQL.

Scope: seeds a single origin for one tenant from one global env var. Multi-tenant
or multi-origin deployments still register additional origins via the sysadmin
API (``POST {api_prefix}/sysadmin/allowed-origins/``).

Revision ID: 202606041200
Revises: 20260603_transcription_migrate
Create Date: 2026-06-04
"""

import logging
import os
from typing import Optional

from sqlalchemy.sql import text

from alembic import op

# revision identifiers, used by Alembic
revision = "202606041200"
down_revision = "20260603_transcription_migrate"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.env")


def _resolve_origin() -> Optional[str]:
    """Return a normalized http(s) origin from the environment, or None.

    Lenient on purpose: a missing or malformed value must skip the backfill, not
    abort the migration. Mirrors the normalization used in ``init_db.py``.
    """
    for candidate in (os.getenv("PUBLIC_ORIGIN"), os.getenv("ORIGIN")):
        if not candidate:
            continue
        origin = candidate.strip().rstrip("/")
        if origin.startswith(("http://", "https://")):
            return origin
    return None


def upgrade() -> None:
    origin = _resolve_origin()
    if origin is None:
        logger.warning(
            "[allowed_origins] PUBLIC_ORIGIN/ORIGIN not set or invalid; "
            "skipping CORS backfill. Frontend origins must be registered "
            "manually via the sysadmin allowed-origins API."
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

    # Unique constraint is (tenant_id, url) since 202602041600_add_api_keys_v2;
    # ON CONFLICT must match it. id/created_at/updated_at have server defaults.
    conn.execute(
        text(
            "INSERT INTO allowed_origins (url, tenant_id) "
            "VALUES (:url, :tenant_id) "
            "ON CONFLICT (tenant_id, url) DO NOTHING"
        ),
        {"url": origin, "tenant_id": tenant_id},
    )

    logger.info(
        "[allowed_origins] Backfilled origin '%s' for tenant '%s'. Additional "
        "origins/tenants must be added via the sysadmin allowed-origins API.",
        origin,
        tenant_name,
    )


def downgrade() -> None:
    # No-op: never delete tenant CORS configuration on downgrade.
    pass
