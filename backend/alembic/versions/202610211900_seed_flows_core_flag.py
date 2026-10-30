"""Seed the flows_core feature flag, off

Every flow surface (REST, packages, settings, the live transcription socket
and the loopback flows MCP server) answers 404 for a tenant without the flag.
It stays off until the integrated flow core is verified; an organisation is
enabled through its tenant flag.

Revision ID: 202610211900
Revises: 202610191005
Create Date: 2026-10-21 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202610211900"
down_revision: str | None = "202610191005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'flows_core',
            'Flows: authoring, publishing and running flows, and their settings',
            false,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM tenant_feature_flags WHERE name = 'flows_core'")
    op.execute("DELETE FROM global_feature_flags WHERE name = 'flows_core'")
