"""Seed whats_new_enabled feature flag

Revision ID: 202609161000
Revises: 202609151000
Create Date: 2026-09-16 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202609161000"
down_revision: str | None = "202609151000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Defaults ON: the feature is opt-out per organisation. Tenants without an
    # explicit preference (including ones created later) follow the global row.
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'whats_new_enabled',
            'Show the What''s new page, release announcement and menu indicator to tenant users',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM tenant_feature_flags WHERE name = 'whats_new_enabled'")
    op.execute("DELETE FROM global_feature_flags WHERE name = 'whats_new_enabled'")
