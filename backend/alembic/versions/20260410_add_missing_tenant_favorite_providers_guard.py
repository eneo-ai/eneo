"""ensure tenant favorite providers column exists

Revision ID: 20260410_fav_prov_guard
Revises: 20260410_merge_heads
Create Date: 2026-04-10 08:40:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_fav_prov_guard"
down_revision = "20260410_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some dev databases were already stamped past the original
    # 20260304 favorite_providers migration without the physical column present.
    # Keep this repair idempotent so fresh databases and repaired dev databases
    # both converge on the model schema expected by Tenants.favorite_providers.
    op.execute(
        """
        ALTER TABLE tenants
        ADD COLUMN IF NOT EXISTS favorite_providers jsonb NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE tenants
        SET favorite_providers = '[]'::jsonb
        WHERE favorite_providers IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tenants
        ALTER COLUMN favorite_providers SET DEFAULT '[]'::jsonb,
        ALTER COLUMN favorite_providers SET NOT NULL
        """
    )


def downgrade() -> None:
    # No-op intentionally: the column is owned by the earlier 20260304 migration
    # in the canonical migration chain. This guard only repairs stamped databases
    # where that migration did not leave the expected physical column behind.
    pass
