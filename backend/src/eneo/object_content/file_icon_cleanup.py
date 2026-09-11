"""Explicit, transactional removal of verified File/Icon legacy columns.

The caller owns a READ COMMITTED transaction and a maintenance window with all
application and worker processes stopped. The 2.2 image supports both states.
"""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.orm import SessionTransaction

from eneo.database.database import AsyncSession
from eneo.database.tables.file_icon_backfill_table import FileIconBackfillAdmissionState


async def file_icon_legacy_is_cleaned(session: AsyncSession) -> bool:
    """Read once per transaction; a reused session must observe later cleanup."""
    transaction = session.sync_session.get_transaction()
    cached = cast(
        tuple[SessionTransaction, bool] | None,
        session.info.get("file_icon_legacy_cleaned"),
    )
    # Retain the object, not its id: later transactions must not reuse this identity.
    if transaction is not None and cached is not None and cached[0] is transaction:
        return cached[1]
    cleaned = bool(
        await session.scalar(
            sa.select(
                FileIconBackfillAdmissionState.legacy_cleaned_at.is_not(None)
            ).where(FileIconBackfillAdmissionState.singleton.is_(True))
        )
    )
    transaction = session.sync_session.get_transaction()
    if transaction is not None:
        session.info["file_icon_legacy_cleaned"] = (transaction, cleaned)
    return cleaned


_LEGACY_COLUMNS = {
    "files": ("text", "blob", "checksum", "size", "transcription"),
    "icons": ("blob", "mimetype", "size"),
}

# These are the four source groups inventoried by 202607231745. Empty values
# are sources; NULL values are absent. Compute integrity inside PostgreSQL.
_SOURCES = """
    SELECT 'file' AS owner_kind, id AS owner_id, tenant_id,
           CASE WHEN file_type = 'text' THEN 'extracted_text'
                WHEN file_type = 'audio' THEN 'original'
                WHEN parent_file_id IS NOT NULL THEN 'derived_page'
                ELSE 'legacy_image' END AS variant,
           CASE WHEN file_type = 'text' THEN convert_to(text, 'UTF8')
                ELSE blob END AS payload
    FROM files
    WHERE CASE WHEN file_type = 'text' THEN text IS NOT NULL
               ELSE blob IS NOT NULL END
    UNION ALL
    SELECT 'file', id, tenant_id, 'original', blob
    FROM files WHERE file_type = 'text' AND blob IS NOT NULL
    UNION ALL
    SELECT 'file', id, tenant_id, 'transcription', convert_to(transcription, 'UTF8')
    FROM files WHERE transcription IS NOT NULL
    UNION ALL
    SELECT 'icon', id, tenant_id, 'primary', blob
    FROM icons WHERE blob IS NOT NULL
"""


class FileIconCleanupRefused(RuntimeError):
    """A verified prerequisite failed; the caller must roll back the transaction."""


def _refuse(
    detail: str,
    *,
    remediation: str = (
        "Repair and complete adoption, or restore the coordinated backup before retrying."
    ),
) -> None:
    raise FileIconCleanupRefused(
        f"File/Icon cleanup refused: {detail}. Legacy storage is preserved. "
        f"{remediation}"
    )


def _require_supported_schema(connection: Connection) -> None:
    columns = set(
        connection.execute(
            sa.text("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name IN ('files', 'icons')
    """)
        )
    )
    if any(
        (table, column) not in columns
        for table, names in _LEGACY_COLUMNS.items()
        for column in names
    ):
        _refuse(
            "the expected legacy columns are missing",
            remediation="Check the schema history and restore its coordinated backup if necessary.",
        )
    if connection.exec_driver_sql("SHOW server_encoding").scalar_one() != "UTF8":
        _refuse(
            "source verification requires UTF8 server encoding",
            remediation="Restore and verify the database with UTF8 encoding before retrying.",
        )


def _require_finished_campaign(connection: Connection) -> None:
    admission = connection.execute(
        sa.text("SELECT paused FROM file_icon_backfill_admission_state WHERE singleton")
    ).all()
    if len(admission) != 1 or admission[0].paused:
        _refuse("admission state is missing or paused")
    if connection.scalar(
        sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM file_icon_backfill_items
            WHERE state NOT IN ('done', 'cancelled')
               OR lease_owner IS NOT NULL OR lease_expires_at IS NOT NULL
        )
    """)
    ):
        _refuse("adoption has unfinished or leased items")
    campaigns = connection.execute(
        sa.text(
            "SELECT state, halt_reason, resume_cursor_id FROM file_icon_backfill_campaign"
        )
    ).all()
    if any(
        row.state != "complete"
        or row.halt_reason is not None
        or row.resume_cursor_id is not None
        for row in campaigns
    ):
        _refuse("the adoption campaign is not complete")
    if not campaigns and connection.scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM file_icon_backfill_items)
            OR EXISTS (SELECT 1 FROM files WHERE text IS NOT NULL OR blob IS NOT NULL OR transcription IS NOT NULL)
            OR EXISTS (SELECT 1 FROM icons WHERE blob IS NOT NULL)
    """)
    ):
        _refuse("legacy sources have not completed an adoption campaign")


def _require_live_source_coverage(connection: Connection) -> None:
    if connection.scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM files WHERE file_type <> 'text' AND text IS NOT NULL)
    """)
    ):
        _refuse("non-text files contain an unsupported legacy text source")
    invalid = connection.execute(
        sa.text(f"""
        WITH sources AS ({_SOURCES})
        SELECT s.owner_kind, s.owner_id, s.variant
        FROM sources s
        LEFT JOIN file_content_references f
          ON s.owner_kind = 'file' AND f.file_id = s.owner_id
         AND f.variant = s.variant AND f.ordinal = 0
        LEFT JOIN icon_content_references icon
          ON s.owner_kind = 'icon' AND icon.icon_id = s.owner_id
         AND icon.variant = s.variant
        LEFT JOIN object_contents c ON c.id = coalesce(f.content_id, icon.content_id)
        LEFT JOIN inline_content_payloads p ON p.content_id = c.id
        LEFT JOIN object_store_objects remote ON remote.content_id = c.id
        WHERE c.state IS DISTINCT FROM 'available'
           OR c.tenant_id IS DISTINCT FROM s.tenant_id
           OR c.delete_requested_at IS NOT NULL OR c.reference_count < 1
           OR c.sha256 IS DISTINCT FROM sha256(s.payload)
           OR c.size_bytes IS DISTINCT FROM octet_length(s.payload)
           OR (c.storage_kind = 'postgres_inline' AND (
               p.content_id IS NULL
               OR sha256(p.payload) IS DISTINCT FROM c.sha256
               OR octet_length(p.payload) IS DISTINCT FROM c.size_bytes
           ))
           OR (c.storage_kind = 'object_store' AND (
               remote.content_id IS NULL
               OR remote.multipart_upload_id IS NOT NULL
               OR octet_length(remote.verification_chunk_sha256) IS DISTINCT FROM
                  32 * greatest(1, (c.size_bytes + remote.verification_chunk_size_bytes - 1)
                                    / remote.verification_chunk_size_bytes)
           ))
        LIMIT 1
    """)
    ).first()
    if invalid is not None:
        _refuse(
            f"{invalid.owner_kind} {invalid.owner_id} variant {invalid.variant} lacks matching available bytes"
        )


def _require_surviving_ledger_references(connection: Connection) -> None:
    invalid = connection.execute(
        sa.text("""
        SELECT i.owner_kind, i.owner_id, i.variant, i.ordinal
        FROM file_icon_backfill_items i
        LEFT JOIN files owner_file ON i.owner_kind = 'file' AND owner_file.id = i.owner_id
        LEFT JOIN icons owner_icon ON i.owner_kind = 'icon' AND owner_icon.id = i.owner_id
        LEFT JOIN file_content_references f
          ON i.owner_kind = 'file' AND f.file_id = i.owner_id
         AND f.variant = i.variant AND f.ordinal = i.ordinal
        LEFT JOIN icon_content_references icon
          ON i.owner_kind = 'icon' AND icon.icon_id = i.owner_id
         AND icon.variant = i.variant AND i.ordinal = 0
        LEFT JOIN object_contents c ON c.id = coalesce(f.content_id, icon.content_id)
        WHERE (owner_file.id IS NOT NULL OR owner_icon.id IS NOT NULL)
          AND (i.state <> 'done'
               OR i.tenant_id IS DISTINCT FROM coalesce(owner_file.tenant_id, owner_icon.tenant_id)
               OR i.content_id IS DISTINCT FROM c.id
               OR c.state IS DISTINCT FROM 'available'
               OR c.tenant_id IS DISTINCT FROM i.tenant_id)
        LIMIT 1
    """)
    ).first()
    if invalid is not None:
        _refuse(
            f"ledger key {invalid.owner_kind} {invalid.owner_id} {invalid.variant}/{invalid.ordinal} has no matching available reference"
        )


def cleanup_file_icon_legacy_storage(connection: Connection) -> bool:
    """Verify and drop legacy columns atomically; return False when already cleaned."""
    if (
        connection.exec_driver_sql("SHOW transaction_isolation").scalar_one()
        != "read committed"
    ):
        _refuse("final verification requires READ COMMITTED transaction isolation")
    previous_lock_timeout = connection.exec_driver_sql("SHOW lock_timeout").scalar_one()
    connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    connection.exec_driver_sql("""
        LOCK TABLE file_icon_backfill_admission_state, file_icon_backfill_campaign,
                   files, icons, file_icon_backfill_items,
                   file_content_references, icon_content_references,
                   object_contents, inline_content_payloads, object_store_objects
        IN ACCESS EXCLUSIVE MODE
    """)
    cleaned = connection.scalar(
        sa.text(
            "SELECT legacy_cleaned_at IS NOT NULL FROM file_icon_backfill_admission_state WHERE singleton"
        )
    )
    if cleaned:
        connection.execute(
            sa.text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": previous_lock_timeout},
        )
        return False
    _require_supported_schema(connection)
    _require_finished_campaign(connection)
    _require_live_source_coverage(connection)
    _require_surviving_ledger_references(connection)
    for table in ("files", "icons"):
        for operation in ("insert", "update"):
            connection.exec_driver_sql(
                f"DROP TRIGGER freeze_{table}_legacy_payload_{operation} ON {table}"
            )
    connection.exec_driver_sql("DROP FUNCTION reject_file_icon_legacy_payload_write()")
    for table, columns in _LEGACY_COLUMNS.items():
        for column in columns:
            connection.exec_driver_sql(f'ALTER TABLE {table} DROP COLUMN "{column}"')
    # Keep the ledger and owner-deletion triggers while this release still owns
    # adoption. The marker prevents fallback and repair from reading dropped data.
    connection.execute(
        sa.text(
            "UPDATE file_icon_backfill_admission_state SET legacy_cleaned_at = clock_timestamp() WHERE singleton"
        )
    )
    connection.execute(
        sa.text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": previous_lock_timeout},
    )
    return True
