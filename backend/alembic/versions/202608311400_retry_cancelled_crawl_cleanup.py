"""retry cancelled crawl transport cleanup

Revision ID: 202608311400
Revises: 202608301030
Create Date: 2026-08-31 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608311400"
down_revision: str | None = "202608301030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_crawl_attempts_transport_cleanup"
_INDEX = "ix_crawl_attempts_pending_transport_cleanup"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "crawl_attempts", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "crawl_attempts",
        "transport_cleaned_at IS NULL OR "
        "failure_code IN ('lease_expired', 'cancelled')",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE crawl_attempts VALIDATE CONSTRAINT {_CONSTRAINT}")

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "crawl_attempts",
            ["finished_at", "id"],
            postgresql_where=sa.text(
                "failure_code IN ('lease_expired', 'cancelled') "
                "AND transport_cleaned_at IS NULL"
            ),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    op.execute("LOCK TABLE crawl_attempts IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM crawl_attempts
                WHERE failure_code = 'cancelled'
                  AND transport_cleaned_at IS NULL
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'cannot downgrade cancelled crawl cleanup',
                    HINT = 'Let the crawler maintenance worker finish cancelled transport cleanup before retrying.';
            END IF;
        END $$;
        """
    )
    op.drop_constraint(_CONSTRAINT, "crawl_attempts", type_="check")
    # The older constraint has no representation for cancelled cleanup receipts.
    # Keep the cancellation outcome; only completed receipts may be removed.
    # Fire the lifecycle trigger now so pending events do not block the DDL.
    op.execute("SET CONSTRAINTS crawl_attempts_preserve_current_attempt IMMEDIATE")
    op.execute(
        "UPDATE crawl_attempts SET transport_cleaned_at = NULL "
        "WHERE failure_code = 'cancelled' AND transport_cleaned_at IS NOT NULL"
    )
    op.create_check_constraint(
        _CONSTRAINT,
        "crawl_attempts",
        "transport_cleaned_at IS NULL OR failure_code = 'lease_expired'",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE crawl_attempts VALIDATE CONSTRAINT {_CONSTRAINT}")

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "crawl_attempts",
            ["finished_at", "id"],
            postgresql_where=sa.text(
                "failure_code = 'lease_expired' AND transport_cleaned_at IS NULL"
            ),
            postgresql_concurrently=True,
        )
