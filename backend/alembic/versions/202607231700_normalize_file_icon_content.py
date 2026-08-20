"""normalize File and Icon bytes into object content

Revision ID: 202607231700
Revises: 202607240310
Create Date: 2026-07-23 17:00:00.000000

The copy phase is resumable and bounded by both
``FILE_ICON_NORMALIZATION_BATCH_ROWS`` and
``FILE_ICON_NORMALIZATION_BATCH_BYTES``. The final authority fence compares
the copied payloads with the legacy columns once while writers wait; operators
should measure that pass on a restored production-size database and reserve a
maintenance window proportional to total File/Icon bytes.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "202607231700"
down_revision: str | None = "202607240310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_INLINE_MAXIMUM_BYTES = 200 * 1024 * 1024
_DEFAULT_BATCH_SIZE = 100
_DEFAULT_BATCH_BYTES = 32 * 1024 * 1024

_PENDING_KEYS_TABLE = "file_icon_normalization_pending"

_CANDIDATE_KEY_FACTS = """
    SELECT
        'file'::text AS owner_kind,
        file.id AS owner_id,
        CASE
            WHEN file.file_type = 'text' THEN 'extracted_text'
            WHEN file.file_type = 'audio' THEN 'original'
            WHEN file.parent_file_id IS NOT NULL THEN 'derived_page'
            ELSE 'legacy_image'
        END AS variant,
        0::integer AS ordinal,
        CASE
            WHEN file.file_type = 'text'
                THEN octet_length(convert_to(file.text, 'UTF8'))
            ELSE octet_length(file.blob)
        END::bigint AS payload_size,
        1::integer AS owner_order
    FROM files AS file
    WHERE NOT EXISTS (
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

    UNION ALL

    SELECT
        'file',
        file.id,
        'original',
        0,
        octet_length(file.blob)::bigint,
        2
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

    UNION ALL

    SELECT
        'file',
        file.id,
        'transcription',
        0,
        octet_length(convert_to(file.transcription, 'UTF8'))::bigint,
        3
    FROM files AS file
    WHERE file.transcription IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM file_content_references AS reference
          WHERE reference.file_id = file.id
            AND reference.variant = 'transcription'
            AND reference.ordinal = 0
      )

    UNION ALL

    SELECT
        'icon',
        icon.id,
        'primary',
        0,
        octet_length(icon.blob)::bigint,
        4
    FROM icons AS icon
    WHERE NOT EXISTS (
        SELECT 1
        FROM icon_content_references AS reference
        WHERE reference.icon_id = icon.id
          AND reference.variant = 'primary'
    )
"""

_DROP_PENDING_KEYS = sa.text(f"DROP TABLE IF EXISTS pg_temp.{_PENDING_KEYS_TABLE}")

_CREATE_PENDING_KEYS = sa.text(f"""
    CREATE TEMPORARY TABLE {_PENDING_KEYS_TABLE} (
        sequence bigint PRIMARY KEY,
        owner_kind text NOT NULL,
        owner_id uuid NOT NULL,
        variant text NOT NULL,
        ordinal integer NOT NULL,
        payload_size bigint NOT NULL
    ) ON COMMIT PRESERVE ROWS
""")

_POPULATE_PENDING_KEYS = sa.text(f"""
    INSERT INTO {_PENDING_KEYS_TABLE} (
        sequence,
        owner_kind,
        owner_id,
        variant,
        ordinal,
        payload_size
    )
    SELECT
        row_number() OVER (
            ORDER BY owner_order, owner_id, variant, ordinal
        ) AS sequence,
        owner_kind,
        owner_id,
        variant,
        ordinal,
        payload_size
    FROM ({_CANDIDATE_KEY_FACTS}) AS candidate
    ORDER BY owner_order, owner_id, variant, ordinal
""")

_CANDIDATE_PAGE = sa.text(f"""
    WITH page AS (
        SELECT pending.*
        FROM {_PENDING_KEYS_TABLE} AS pending
        WHERE pending.sequence > :after_sequence
        ORDER BY pending.sequence
        LIMIT :batch_size
    ),
    bounded AS (
        SELECT
            page.*,
            sum(page.payload_size) OVER (
                ORDER BY page.sequence
                ROWS UNBOUNDED PRECEDING
            ) AS running_size
        FROM page
    ),
    selected AS (
        SELECT bounded.*
        FROM bounded
        WHERE bounded.sequence = (SELECT min(sequence) FROM bounded)
           OR bounded.running_size <= :batch_bytes
    )
    SELECT
        selected.sequence,
        selected.owner_kind,
        selected.owner_id,
        CASE
            WHEN selected.owner_kind = 'icon' THEN icon.tenant_id
            ELSE file.tenant_id
        END AS tenant_id,
        CASE
            WHEN selected.owner_kind = 'icon' THEN NULL::uuid
            ELSE file.user_id
        END AS created_by_user_id,
        selected.variant,
        selected.ordinal,
        CASE
            WHEN selected.owner_kind = 'icon' THEN icon.mimetype
            WHEN selected.variant = 'transcription' THEN 'text/plain'
            WHEN selected.variant = 'original' THEN COALESCE(
                NULLIF(file.mimetype, ''),
                'application/octet-stream'
            )
            WHEN file.file_type = 'text' THEN 'text/plain'
            ELSE COALESCE(
                NULLIF(file.mimetype, ''),
                'application/octet-stream'
            )
        END AS media_type,
        selected.payload_size,
        CASE
            WHEN selected.owner_kind = 'icon' THEN icon.blob
            WHEN selected.variant = 'transcription'
                THEN convert_to(file.transcription, 'UTF8')
            WHEN selected.variant = 'original' THEN file.blob
            WHEN file.file_type = 'text' THEN convert_to(file.text, 'UTF8')
            ELSE file.blob
        END AS payload
    FROM selected
    LEFT JOIN files AS file
      ON selected.owner_kind = 'file' AND file.id = selected.owner_id
    LEFT JOIN icons AS icon
      ON selected.owner_kind = 'icon' AND icon.id = selected.owner_id
    ORDER BY selected.sequence
""")

_FIRST_CANDIDATE = sa.text(f"""
    SELECT owner_kind, owner_id
    FROM ({_CANDIDATE_KEY_FACTS}) AS candidate
    ORDER BY owner_order, owner_id, variant, ordinal
    LIMIT 1
""")

_INSERT_BATCH = sa.text(f"""
    WITH selected AS (
        {_CANDIDATE_PAGE.text}
    ),
    normalized AS (
        SELECT
            selected.*,
            gen_random_uuid() AS content_id,
            sha256(selected.payload) AS sha256,
            'normalize:' || selected.owner_kind || ':'
                || selected.owner_id::text || ':' || selected.variant || ':'
                || selected.ordinal::text AS idempotency_key
        FROM selected
    ),
    batch AS (
        SELECT
            normalized.*,
            sha256(
                convert_to('eneo-file-icon-normalization-v1', 'UTF8')
                || decode('00', 'hex')
                || convert_to(normalized.idempotency_key, 'UTF8')
                || normalized.sha256
            ) AS request_fingerprint
        FROM normalized
    ),
    controls AS (
        INSERT INTO object_contents (
            id,
            tenant_id,
            created_by_user_id,
            storage_kind,
            state,
            access_class,
            sha256,
            size_bytes,
            declared_media_type,
            verified_media_type,
            idempotency_key,
            request_fingerprint,
            available_at
        )
        SELECT
            batch.content_id,
            batch.tenant_id,
            batch.created_by_user_id,
            'postgres_inline',
            'available',
            CASE
                WHEN batch.owner_kind = 'icon'
                    THEN 'public_immutable'
                ELSE 'private_resource'
            END,
            batch.sha256,
            batch.payload_size,
            batch.media_type,
            batch.media_type,
            batch.idempotency_key,
            batch.request_fingerprint,
            now()
        FROM batch
        RETURNING id
    ),
    payloads AS (
        INSERT INTO inline_content_payloads (
            content_id,
            storage_kind,
            payload
        )
        SELECT batch.content_id, 'postgres_inline', batch.payload
        FROM batch
        JOIN controls ON controls.id = batch.content_id
        RETURNING content_id
    ),
    file_references AS (
        INSERT INTO file_content_references (
            file_id,
            content_id,
            variant,
            ordinal
        )
        SELECT
            batch.owner_id,
            batch.content_id,
            batch.variant,
            batch.ordinal
        FROM batch
        JOIN payloads ON payloads.content_id = batch.content_id
        WHERE batch.owner_kind = 'file'
        RETURNING content_id
    ),
    icon_references AS (
        INSERT INTO icon_content_references (
            icon_id,
            content_id,
            variant
        )
        SELECT batch.owner_id, batch.content_id, 'primary'
        FROM batch
        JOIN payloads ON payloads.content_id = batch.content_id
        WHERE batch.owner_kind = 'icon'
        RETURNING content_id
    )
    SELECT
        (SELECT count(*) FROM file_references)
        + (SELECT count(*) FROM icon_references) AS inserted_count,
        (SELECT count(*) FROM batch) AS expected_count,
        (SELECT max(sequence) FROM batch) AS last_sequence
""")


def _positive_setting(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _preflight_legacy_rows(connection: Connection, inline_limit: int) -> None:
    invalid = connection.execute(
        sa.text("""
            SELECT id, file_type
            FROM files
            WHERE file_type NOT IN ('text', 'image', 'audio')
               OR (
                    file_type = 'text'
                    AND text IS NULL
               )
               OR (
                    file_type IN ('image', 'audio')
                    AND (blob IS NULL OR text IS NOT NULL)
               )
            ORDER BY id
            LIMIT 1
        """)
    ).one_or_none()
    if invalid is not None:
        raise RuntimeError(
            "File/Icon normalization found an ambiguous File row "
            f"{invalid.id} ({invalid.file_type}); classify it before retrying"
        )

    invalid_icon = connection.execute(
        sa.text("""
            SELECT id
            FROM icons
            WHERE blob IS NULL OR NULLIF(btrim(mimetype), '') IS NULL
            ORDER BY id
            LIMIT 1
        """)
    ).scalar_one_or_none()
    if invalid_icon is not None:
        raise RuntimeError(
            "File/Icon normalization found Icon "
            f"{invalid_icon} without bytes or a media type; repair it before retrying"
        )

    unexpected_reference = connection.execute(
        sa.text("""
            SELECT owner_kind, owner_id, idempotency_key
            FROM (
                SELECT
                    'file'::text AS owner_kind,
                    reference.file_id AS owner_id,
                    content.idempotency_key
                FROM file_content_references AS reference
                JOIN object_contents AS content
                  ON content.id = reference.content_id
                UNION ALL
                SELECT
                    'icon',
                    reference.icon_id,
                    content.idempotency_key
                FROM icon_content_references AS reference
                JOIN object_contents AS content
                  ON content.id = reference.content_id
            ) AS existing
            WHERE idempotency_key NOT LIKE 'normalize:%'
            ORDER BY owner_kind, owner_id
            LIMIT 1
        """)
    ).one_or_none()
    if unexpected_reference is not None:
        raise RuntimeError(
            "File/Icon normalization found a pre-existing "
            f"{unexpected_reference.owner_kind} content reference for "
            f"{unexpected_reference.owner_id}; stop concurrent producers and "
            "resolve its byte authority before retrying"
        )

    oversized = connection.execute(
        sa.text("""
            WITH payloads AS (
                SELECT
                    'file'::text AS owner_kind,
                    id AS owner_id,
                    CASE
                        WHEN file_type = 'text'
                            THEN octet_length(convert_to(text, 'UTF8'))
                        ELSE octet_length(blob)
                    END::bigint AS size_bytes
                FROM files
                UNION ALL
                SELECT 'file-original', id, octet_length(blob)::bigint
                FROM files
                WHERE file_type = 'text'
                  AND blob IS NOT NULL
                UNION ALL
                SELECT 'file-transcription', id,
                       octet_length(convert_to(transcription, 'UTF8'))::bigint
                FROM files
                WHERE transcription IS NOT NULL
                UNION ALL
                SELECT 'icon', id, octet_length(blob)::bigint
                FROM icons
            )
            SELECT owner_kind, owner_id, size_bytes
            FROM payloads
            WHERE size_bytes > :inline_limit
            ORDER BY size_bytes DESC, owner_id
            LIMIT 1
        """),
        {"inline_limit": inline_limit},
    ).one_or_none()
    if oversized is not None:
        raise RuntimeError(
            "File/Icon normalization payload "
            f"{oversized.owner_kind}:{oversized.owner_id} is "
            f"{oversized.size_bytes} bytes, above "
            f"OBJECT_CONTENT_INLINE_MAXIMUM_BYTES={inline_limit}; "
            "raise the operator ceiling after capacity review and retry"
        )


def _stage_pending_keys(connection: Connection) -> None:
    """Snapshot missing owner/variant keys without materializing payload bytes."""
    connection.execute(_DROP_PENDING_KEYS)
    connection.execute(_CREATE_PENDING_KEYS)
    connection.execute(_POPULATE_PENDING_KEYS)


def _copy_in_bounded_batches(
    connection: Connection,
    *,
    batch_size: int,
    batch_bytes: int,
) -> None:
    _stage_pending_keys(connection)
    after_sequence = 0
    while True:
        result = connection.execute(
            _INSERT_BATCH,
            {
                "after_sequence": after_sequence,
                "batch_size": batch_size,
                "batch_bytes": batch_bytes,
            },
        ).one()
        expected_count = int(result.expected_count)
        if expected_count == 0:
            return

        if int(result.inserted_count) != expected_count:
            raise RuntimeError(
                "File/Icon normalization did not attach every copied payload"
            )
        after_sequence = int(result.last_sequence)


def _assert_copy_matches_legacy(connection: Connection) -> None:
    mismatch = connection.execute(
        sa.text("""
            WITH expected AS (
                SELECT
                    reference.content_id,
                    CASE
                        WHEN reference.variant = 'transcription'
                            THEN convert_to(file.transcription, 'UTF8')
                        WHEN reference.variant = 'original'
                            THEN file.blob
                        WHEN file.file_type = 'text'
                            THEN convert_to(file.text, 'UTF8')
                        ELSE file.blob
                    END AS legacy_payload
                FROM file_content_references AS reference
                JOIN files AS file ON file.id = reference.file_id
                JOIN object_contents AS content
                  ON content.id = reference.content_id
                WHERE reference.variant IN (
                    'extracted_text',
                    'transcription',
                    'original',
                    'derived_page',
                    'model_input',
                    'legacy_image'
                )
                  AND content.idempotency_key LIKE 'normalize:%'
                UNION ALL
                SELECT reference.content_id, icon.blob
                FROM icon_content_references AS reference
                JOIN icons AS icon ON icon.id = reference.icon_id
                JOIN object_contents AS content
                  ON content.id = reference.content_id
                WHERE reference.variant = 'primary'
                  AND content.idempotency_key LIKE 'normalize:%'
            )
            SELECT expected.content_id
            FROM expected
            JOIN object_contents AS content
              ON content.id = expected.content_id
            JOIN inline_content_payloads AS inline
              ON inline.content_id = expected.content_id
            WHERE content.storage_kind <> 'postgres_inline'
               OR content.state <> 'available'
               OR inline.payload IS DISTINCT FROM expected.legacy_payload
               OR content.size_bytes <> octet_length(expected.legacy_payload)
            ORDER BY expected.content_id
            LIMIT 1
        """)
    ).scalar_one_or_none()
    if mismatch is not None:
        raise RuntimeError(
            f"File/Icon normalization verification failed for content {mismatch}"
        )


def _verify_canonical_digests(connection: Connection) -> None:
    rows = connection.execute(
        sa.text("""
            SELECT content.id, content.sha256, content.size_bytes, inline.payload
            FROM object_contents AS content
            JOIN inline_content_payloads AS inline
              ON inline.content_id = content.id
            WHERE content.idempotency_key LIKE 'normalize:%'
            ORDER BY content.id
        """),
        execution_options={"stream_results": True},
    )
    try:
        for row in rows:
            payload = bytes(row.payload)
            if len(payload) != row.size_bytes or sha256(payload).digest() != bytes(
                row.sha256
            ):
                raise RuntimeError(
                    "File/Icon normalization canonical digest verification failed "
                    f"for content {row.id}"
                )
    finally:
        rows.close()


def _assert_no_concurrent_legacy_write(
    connection: Connection,
) -> None:
    candidate = connection.execute(
        _FIRST_CANDIDATE,
    ).first()
    if candidate is not None:
        raise RuntimeError(
            "File/Icon normalization detected a concurrent File/Icon write "
            f"for {candidate.owner_kind}:{candidate.owner_id}; legacy columns "
            "remain authoritative, stop producers and retry"
        )


def upgrade() -> None:
    connection = op.get_bind()
    inline_limit = _positive_setting(
        "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
        _DEFAULT_INLINE_MAXIMUM_BYTES,
    )
    batch_size = _positive_setting(
        "FILE_ICON_NORMALIZATION_BATCH_ROWS",
        _DEFAULT_BATCH_SIZE,
    )
    batch_bytes = _positive_setting(
        "FILE_ICON_NORMALIZATION_BATCH_BYTES",
        _DEFAULT_BATCH_BYTES,
    )
    _preflight_legacy_rows(connection, inline_limit)

    op.drop_constraint(
        "ck_file_content_references_variant",
        "file_content_references",
        type_="check",
    )
    op.create_check_constraint(
        "ck_file_content_references_variant",
        "file_content_references",
        "variant IN ('original', 'extracted_text', 'transcription', "
        "'derived_page', 'model_input', 'generated_artifact', "
        "'legacy_image', 'preview')",
    )

    # Each bounded batch is one atomic statement in autocommit mode. A stopped
    # migration leaves legacy columns authoritative and reruns skip committed
    # references before the final transactional contraction.
    with op.get_context().autocommit_block():
        _copy_in_bounded_batches(
            connection,
            batch_size=batch_size,
            batch_bytes=batch_bytes,
        )

    # The copied rows are immutable normalization artifacts. Recompute every
    # canonical digest before taking the final legacy write fence so total
    # byte hashing never extends the exclusive-lock window.
    _verify_canonical_digests(connection)

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_files_checksum")

    # Fence both legacy owners before the final scan and keep the lock through
    # contraction. A transaction that began before the fence either commits
    # first and is detected below, or rolls back. Later writers wait until the
    # legacy columns are gone and then fail instead of creating a second truth.
    op.execute("LOCK TABLE files, icons IN ACCESS EXCLUSIVE MODE")
    _preflight_legacy_rows(connection, inline_limit)
    _assert_no_concurrent_legacy_write(connection)
    _assert_copy_matches_legacy(connection)

    op.drop_column("files", "text")
    op.drop_column("files", "blob")
    op.drop_column("files", "checksum")
    op.drop_column("files", "size")
    op.drop_column("files", "transcription")
    op.drop_column("icons", "blob")
    op.drop_column("icons", "mimetype")
    op.drop_column("icons", "size")


def downgrade() -> None:
    raise RuntimeError(
        "File/Icon content authority has been flipped to object content. "
        "Downgrade would discard typed variants; restore the pre-flip backup "
        "or recover forward instead."
    )
