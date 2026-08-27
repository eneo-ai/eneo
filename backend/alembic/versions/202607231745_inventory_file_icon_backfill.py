"""inventory frozen File and Icon legacy payloads

Revision ID: 202607231745
Revises: 202607231700
Create Date: 2026-07-23 17:45:00.000000

The preceding expand revision installs the legacy-write fence. Entering the
autocommit block commits that schema work before any owner scan begins, so the
inventory never inherits ACCESS EXCLUSIVE locks on ``files`` or ``icons``.

Each variant group commits independently and ignores already-inventoried keys.
An interrupted run can therefore resume without duplicating ledger items.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607231745"
down_revision: str | None = "202607231700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFLICT = """
ON CONFLICT ON CONSTRAINT uq_file_icon_backfill_items_owner_variant
DO NOTHING
"""


def _inventory_primary_file_payloads() -> None:
    op.execute(
        f"""
        INSERT INTO file_icon_backfill_items (
            owner_kind,
            owner_id,
            variant,
            ordinal,
            tenant_id,
            payload_size_estimate
        )
        SELECT
            'file',
            file.id,
            CASE
                WHEN file.file_type = 'text' THEN 'extracted_text'
                WHEN file.file_type = 'audio' THEN 'original'
                WHEN file.parent_file_id IS NOT NULL THEN 'derived_page'
                ELSE 'legacy_image'
            END,
            0,
            file.tenant_id,
            file.size::bigint
        FROM files AS file
        WHERE CASE
                  WHEN file.file_type = 'text' THEN file.text IS NOT NULL
                  ELSE file.blob IS NOT NULL
              END
          AND NOT EXISTS (
              SELECT 1
              FROM file_content_references AS reference
              WHERE reference.file_id = file.id
                AND reference.variant = CASE
                    WHEN file.file_type = 'text' THEN 'extracted_text'
                    WHEN file.file_type = 'audio' THEN 'original'
                    WHEN file.parent_file_id IS NOT NULL THEN 'derived_page'
                    ELSE 'legacy_image'
                END
                AND reference.ordinal = 0
          )
        {_CONFLICT}
        """
    )


def _inventory_text_originals() -> None:
    op.execute(
        f"""
        INSERT INTO file_icon_backfill_items (
            owner_kind,
            owner_id,
            variant,
            ordinal,
            tenant_id,
            payload_size_estimate
        )
        SELECT 'file', file.id, 'original', 0, file.tenant_id,
               pg_column_size(file.blob)::bigint
        FROM files AS file
        WHERE file.file_type = 'text'
          AND file.blob IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM file_content_references AS reference
              WHERE reference.file_id = file.id
                AND reference.variant = 'original'
                AND reference.ordinal = 0
          )
        {_CONFLICT}
        """
    )


def _inventory_transcriptions() -> None:
    op.execute(
        f"""
        INSERT INTO file_icon_backfill_items (
            owner_kind,
            owner_id,
            variant,
            ordinal,
            tenant_id,
            payload_size_estimate
        )
        SELECT 'file', file.id, 'transcription', 0, file.tenant_id,
               pg_column_size(file.transcription)::bigint
        FROM files AS file
        WHERE file.transcription IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM file_content_references AS reference
              WHERE reference.file_id = file.id
                AND reference.variant = 'transcription'
                AND reference.ordinal = 0
          )
        {_CONFLICT}
        """
    )


def _inventory_icons() -> None:
    op.execute(
        f"""
        INSERT INTO file_icon_backfill_items (
            owner_kind,
            owner_id,
            variant,
            ordinal,
            tenant_id,
            payload_size_estimate
        )
        SELECT 'icon', icon.id, 'primary', 0, icon.tenant_id,
               icon.size::bigint
        FROM icons AS icon
        WHERE icon.blob IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM icon_content_references AS reference
              WHERE reference.icon_id = icon.id
                AND reference.variant = 'primary'
          )
        {_CONFLICT}
        """
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _inventory_primary_file_payloads()
        _inventory_text_originals()
        _inventory_transcriptions()
        _inventory_icons()
        op.execute("ANALYZE file_icon_backfill_items")


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon staged backfill inventory may already be in use. Recover "
        "forward or restore the coordinated pre-upgrade backup."
    )
