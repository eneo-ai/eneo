"""remove legacy module feature-flag state

Revision ID: 202608251000
Revises: 202608211300
Create Date: 2026-08-25 10:00:00.000000

The module registry is now owned exclusively by the module-auth installation
lifecycle. Tenant assignments with no auth-client configuration are remnants
of the retired feature-flag system (or unusable partial writes) and must not be
presented as installations in the new administration UI.

``SWE Models`` is removed regardless of configuration because its space makes
it unroutable by the module-auth contract. ``eneo-applications`` is retained
when it has real auth-client configuration, so an installation that adopted
the old key is not deleted merely because of its name.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608251000"
down_revision: str = "202608211300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM tenants_modules AS assignment
            USING modules AS module
            WHERE assignment.module_id = module.id
              AND (
                (
                  assignment.redirect_uris IS NULL
                  AND assignment.service_key_id IS NULL
                )
                OR module.name = 'SWE Models'
              )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM modules AS module
            WHERE module.name IN ('eneo-applications', 'SWE Models')
              AND NOT EXISTS (
                SELECT 1
                FROM tenants_modules AS assignment
                WHERE assignment.module_id = module.id
              )
            """
        )
    )


def downgrade() -> None:
    # Removed tenant assignments cannot be reconstructed safely. Re-seeding
    # identities without their original tenant ownership would be misleading,
    # and the retired feature-gate code no longer consumes them.
    pass
