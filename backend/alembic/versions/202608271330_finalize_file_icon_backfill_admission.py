"""finalize File/Icon backfill admission before capacity gating

Revision ID: 202608271330
Revises: 202608261800
Create Date: 2026-08-27 13:30:00.000000

The worker now resolves deleted owners and already-available references in
bounded batches before it freezes the inline capacity requirement. Rows that
still need legacy bytes enter the explicit ``ready`` state. Delete triggers
cancel unfinished ledger rows so a deployment waiting for capacity or object
storage can still converge when its remaining owners disappear.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608271330"
down_revision: str | None = "202608261800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_file_icon_backfill_items_state",
        "file_icon_backfill_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_file_icon_backfill_items_state",
        "file_icon_backfill_items",
        "state IN ('pending', 'ready', 'leased', 'failed', 'done', 'cancelled')",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        CREATE FUNCTION cancel_deleted_file_icon_backfill_owner()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
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
            RETURN OLD;
        END;
        $$;

        CREATE TRIGGER cancel_deleted_file_backfill_owner
        BEFORE DELETE ON files
        FOR EACH ROW
        EXECUTE FUNCTION cancel_deleted_file_icon_backfill_owner();

        CREATE TRIGGER cancel_deleted_icon_backfill_owner
        BEFORE DELETE ON icons
        FOR EACH ROW
        EXECUTE FUNCTION cancel_deleted_file_icon_backfill_owner();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon adoption may already have finalized admission or cancelled "
        "ledger rows after owner deletion. Recover forward or restore the "
        "coordinated pre-upgrade backup."
    )
