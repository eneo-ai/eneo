"""prepare staged File and Icon object-content backfill

Revision ID: 202607231700
Revises: 202607240310
Create Date: 2026-07-23 17:00:00.000000

This revision replaces the unreleased offline normalization at the same
revision ID. It prepares a ledger without copying payload bytes, retains every
legacy column, and freezes those payload facts for an online, resumable
backfill. The following revision populates the ledger after this schema change
has committed.

An environment that already applied the former version of revision
``202607231700`` must restore its pre-upgrade backup before using this chain.
Alembic cannot distinguish the former destructive revision from this expand
revision because they intentionally share an unreleased revision ID.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607231700"
down_revision: str | None = "202607240310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FILE_VARIANTS = (
    "'original', 'extracted_text', 'transcription', 'derived_page', "
    "'model_input', 'generated_artifact', 'legacy_image', 'preview'"
)


def _create_backfill_tables() -> None:
    op.create_table(
        "file_icon_backfill_items",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column("owner_kind", sa.String(length=16), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload_size_estimate", sa.BigInteger(), nullable=False),
        sa.Column(
            "state", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_detail", sa.String(length=512), nullable=True),
        sa.Column(
            "content_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("object_contents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_kind IN ('file', 'icon')",
            name="ck_file_icon_backfill_items_owner_kind",
        ),
        sa.CheckConstraint(
            f"variant IN ({_FILE_VARIANTS}, 'primary')",
            name="ck_file_icon_backfill_items_variant",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_file_icon_backfill_items_ordinal"),
        sa.CheckConstraint(
            "payload_size_estimate >= 0",
            name="ck_file_icon_backfill_items_payload_size",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'leased', 'failed', 'done', 'cancelled')",
            name="ck_file_icon_backfill_items_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_file_icon_backfill_items_attempts"
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_file_icon_backfill_items_lease_pair",
        ),
        sa.CheckConstraint(
            "(state = 'done') = (content_id IS NOT NULL)",
            name="ck_file_icon_backfill_items_done_content",
        ),
        sa.CheckConstraint(
            "last_error_detail IS NULL OR char_length(last_error_detail) <= 512",
            name="ck_file_icon_backfill_items_error_detail",
        ),
        sa.UniqueConstraint(
            "owner_kind",
            "owner_id",
            "variant",
            "ordinal",
            name="uq_file_icon_backfill_items_owner_variant",
        ),
    )
    op.create_index(
        "ix_file_icon_backfill_items_claim",
        "file_icon_backfill_items",
        ["state", "lease_expires_at", "id"],
    )

    op.create_table(
        "file_icon_backfill_campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("destination_revision", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("halt_reason", sa.String(length=512), nullable=True),
        sa.CheckConstraint(
            "target_kind IN ('postgres_inline', 'object_store')",
            name="ck_file_icon_backfill_campaign_target",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'halted', 'complete')",
            name="ck_file_icon_backfill_campaign_state",
        ),
        sa.CheckConstraint(
            "(target_kind = 'postgres_inline' AND destination_revision IS NULL) "
            "OR (target_kind = 'object_store' AND destination_revision IS NOT NULL)",
            name="ck_file_icon_backfill_campaign_destination",
        ),
        sa.CheckConstraint(
            "halt_reason IS NULL OR char_length(halt_reason) <= 512",
            name="ck_file_icon_backfill_campaign_halt_reason",
        ),
    )
    op.create_index(
        "uq_file_icon_backfill_campaign_singleton",
        "file_icon_backfill_campaign",
        [sa.text("(true)")],
        unique=True,
    )


def _install_legacy_freeze() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_file_icon_legacy_payload_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION
                    'legacy payload writes are frozen by File/Icon staged backfill Release A'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_TABLE_NAME = 'files' THEN
                IF NEW.text IS NOT NULL
                     OR NEW.blob IS NOT NULL
                     OR NEW.transcription IS NOT NULL
                     OR NEW.checksum IS NOT NULL
                     OR NEW.size IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'legacy payload writes are frozen by File/Icon staged backfill Release A'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF TG_TABLE_NAME = 'icons' THEN
                IF NEW.blob IS NOT NULL
                     OR NEW.mimetype IS NOT NULL
                     OR NEW.size IS NOT NULL
                THEN
                    RAISE EXCEPTION
                        'legacy payload writes are frozen by File/Icon staged backfill Release A'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER freeze_files_legacy_payload_insert
        BEFORE INSERT ON files
        FOR EACH ROW
        EXECUTE FUNCTION reject_file_icon_legacy_payload_write();

        CREATE TRIGGER freeze_files_legacy_payload_update
        BEFORE UPDATE OF text, blob, transcription, checksum, size ON files
        FOR EACH ROW
        EXECUTE FUNCTION reject_file_icon_legacy_payload_write();

        CREATE TRIGGER freeze_icons_legacy_payload_insert
        BEFORE INSERT ON icons
        FOR EACH ROW
        EXECUTE FUNCTION reject_file_icon_legacy_payload_write();

        CREATE TRIGGER freeze_icons_legacy_payload_update
        BEFORE UPDATE OF blob, mimetype, size ON icons
        FOR EACH ROW
        EXECUTE FUNCTION reject_file_icon_legacy_payload_write();
        """
    )


def upgrade() -> None:
    op.drop_constraint(
        "ck_file_content_references_variant",
        "file_content_references",
        type_="check",
    )
    op.create_check_constraint(
        "ck_file_content_references_variant",
        "file_content_references",
        f"variant IN ({_FILE_VARIANTS})",
    )

    for column in ("text", "blob", "checksum", "size", "transcription"):
        op.alter_column("files", column, nullable=True)
    for column in ("blob", "mimetype", "size"):
        op.alter_column("icons", column, nullable=True)

    _create_backfill_tables()
    _install_legacy_freeze()


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon staged backfill may already have accepted object-content-only "
        "writes. Recover forward or restore the coordinated pre-upgrade backup."
    )
