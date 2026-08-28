"""track durable File/Icon backfill admission changes

Revision ID: 202608281000
Revises: 202608271330
Create Date: 2026-08-28 10:00:00.000000

Capacity waits are cached between scheduled worker runs. This revision adds a
transactional singleton generation and advances it when an owner deletion
changes the pre-campaign capacity total, allowing the worker to invalidate the
cache in O(1). Once a campaign exists, deletion no longer needs the admission
fence or its deployment-global row lock.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608281000"
down_revision: str | None = "202608271330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_icon_backfill_admission_state",
        sa.Column(
            "singleton",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "generation",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.CheckConstraint(
            "singleton",
            name="ck_file_icon_backfill_admission_singleton",
        ),
        sa.CheckConstraint(
            "generation >= 0",
            name="ck_file_icon_backfill_admission_generation",
        ),
    )
    op.execute(
        """
        INSERT INTO file_icon_backfill_admission_state (singleton, generation)
        VALUES (true, 0);

        CREATE OR REPLACE FUNCTION cancel_deleted_file_icon_backfill_owner()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            campaign_exists boolean;
            cancelled_count integer;
            cancelled_ready boolean := false;
        BEGIN
            SELECT EXISTS (SELECT 1 FROM file_icon_backfill_campaign)
            INTO campaign_exists;

            IF NOT campaign_exists THEN
                PERFORM generation
                FROM file_icon_backfill_admission_state
                WHERE singleton
                FOR UPDATE;

                SELECT EXISTS (SELECT 1 FROM file_icon_backfill_campaign)
                INTO campaign_exists;

                IF NOT campaign_exists THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM file_icon_backfill_items
                        WHERE owner_kind = CASE TG_TABLE_NAME
                                WHEN 'files' THEN 'file'
                                ELSE 'icon'
                            END
                          AND owner_id = OLD.id
                          AND state = 'ready'
                    )
                    INTO cancelled_ready;
                END IF;
            END IF;

            UPDATE file_icon_backfill_items
            SET state = 'cancelled',
                content_id = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error_code = NULL,
                last_error_detail = NULL,
                failure_revision = NULL,
                updated_at = clock_timestamp()
            WHERE owner_kind = CASE TG_TABLE_NAME
                    WHEN 'files' THEN 'file'
                    ELSE 'icon'
                END
              AND owner_id = OLD.id
              AND state IN ('pending', 'ready', 'failed', 'done');

            GET DIAGNOSTICS cancelled_count = ROW_COUNT;
            IF cancelled_ready AND cancelled_count > 0 THEN
                UPDATE file_icon_backfill_admission_state
                SET generation = generation + 1
                WHERE singleton;
            END IF;
            RETURN OLD;
        END;
        $$;

        DROP TRIGGER cancel_deleted_file_backfill_owner ON files;
        CREATE TRIGGER cancel_deleted_file_backfill_owner
        BEFORE DELETE ON files
        FOR EACH ROW
        EXECUTE FUNCTION cancel_deleted_file_icon_backfill_owner();

        DROP TRIGGER cancel_deleted_icon_backfill_owner ON icons;
        CREATE TRIGGER cancel_deleted_icon_backfill_owner
        BEFORE DELETE ON icons
        FOR EACH ROW
        EXECUTE FUNCTION cancel_deleted_file_icon_backfill_owner();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon admission cache generations may already have advanced. "
        "Recover forward or restore the coordinated pre-upgrade backup."
    )
