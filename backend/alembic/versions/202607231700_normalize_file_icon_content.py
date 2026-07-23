"""normalize File and Icon bytes into object content

Revision ID: 202607231700
Revises: 202607231200
Create Date: 2026-07-23 17:00:00.000000
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Sequence
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Row

from alembic import op

revision: str = "202607231700"
down_revision: str | None = "202607231200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_INLINE_MAXIMUM_BYTES = 10 * 1024 * 1024
_DEFAULT_BATCH_SIZE = 100

_CANDIDATES = sa.text("""
    WITH candidate_facts AS (
        SELECT
            'file'::text AS owner_kind,
            file.id AS owner_id,
            file.tenant_id,
            file.user_id AS created_by_user_id,
            CASE
                WHEN file.file_type = 'text' THEN 'extracted_text'
                WHEN file.file_type = 'audio' THEN 'original'
                WHEN file.parent_file_id IS NOT NULL THEN 'derived_page'
                ELSE 'model_input'
            END AS variant,
            0::integer AS ordinal,
            CASE
                WHEN file.file_type = 'text' THEN 'text/plain'
                ELSE COALESCE(NULLIF(file.mimetype, ''), 'application/octet-stream')
            END AS media_type,
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
                    ELSE 'model_input'
                  END
              AND reference.ordinal = 0
        )

        UNION ALL

        SELECT
            'file',
            file.id,
            file.tenant_id,
            file.user_id,
            'transcription',
            0,
            'text/plain',
            octet_length(convert_to(file.transcription, 'UTF8'))::bigint,
            2
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
            icon.tenant_id,
            NULL::uuid,
            'primary',
            0,
            icon.mimetype,
            octet_length(icon.blob)::bigint,
            3
        FROM icons AS icon
        WHERE NOT EXISTS (
            SELECT 1
            FROM icon_content_references AS reference
            WHERE reference.icon_id = icon.id
              AND reference.variant = 'primary'
        )
    ),
    bounded AS (
        SELECT
            facts.*,
            row_number() OVER (
                ORDER BY owner_order, owner_id, variant, ordinal
            ) AS row_number,
            sum(payload_size) OVER (
                ORDER BY owner_order, owner_id, variant, ordinal
                ROWS UNBOUNDED PRECEDING
            ) AS running_size
        FROM candidate_facts AS facts
    )
    SELECT
        bounded.owner_kind,
        bounded.owner_id,
        bounded.tenant_id,
        bounded.created_by_user_id,
        bounded.variant,
        bounded.ordinal,
        bounded.media_type,
        bounded.payload_size,
        CASE
            WHEN bounded.owner_kind = 'icon' THEN icon.blob
            WHEN bounded.variant = 'transcription'
                THEN convert_to(file.transcription, 'UTF8')
            WHEN file.file_type = 'text' THEN convert_to(file.text, 'UTF8')
            ELSE file.blob
        END AS payload
    FROM bounded
    LEFT JOIN files AS file
      ON bounded.owner_kind = 'file' AND file.id = bounded.owner_id
    LEFT JOIN icons AS icon
      ON bounded.owner_kind = 'icon' AND icon.id = bounded.owner_id
    WHERE bounded.row_number = 1 OR bounded.running_size <= :batch_bytes
    ORDER BY bounded.owner_order, bounded.owner_id, bounded.variant, bounded.ordinal
    LIMIT :batch_size
""")

_INSERT_BATCH = sa.text("""
    WITH batch AS (
        SELECT
            record.content_id::uuid AS content_id,
            record.owner_kind,
            record.owner_id::uuid AS owner_id,
            record.tenant_id::uuid AS tenant_id,
            NULLIF(record.created_by_user_id, '')::uuid AS created_by_user_id,
            record.variant,
            record.ordinal,
            record.media_type,
            decode(record.payload_base64, 'base64') AS payload,
            decode(record.sha256_hex, 'hex') AS sha256,
            record.size_bytes,
            record.idempotency_key,
            decode(record.request_fingerprint_hex, 'hex') AS request_fingerprint
        FROM jsonb_to_recordset(CAST(:batch AS jsonb)) AS record(
            content_id text,
            owner_kind text,
            owner_id text,
            tenant_id text,
            created_by_user_id text,
            variant text,
            ordinal integer,
            media_type text,
            payload_base64 text,
            sha256_hex text,
            size_bytes bigint,
            idempotency_key text,
            request_fingerprint_hex text
        )
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
            batch.size_bytes,
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
        + (SELECT count(*) FROM icon_references) AS inserted_count
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
                    AND (text IS NULL OR blob IS NOT NULL)
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


def _normalization_record(row: Row[object]) -> dict[str, object]:
    payload = bytes(row.payload)
    digest = sha256(payload).digest()
    content_id = uuid4()
    idempotency_key = (
        f"normalize:{row.owner_kind}:{row.owner_id}:{row.variant}:{row.ordinal}"
    )
    request_fingerprint = sha256(
        b"eneo-file-icon-normalization-v1\0" + idempotency_key.encode() + digest
    ).digest()
    return {
        "content_id": str(content_id),
        "owner_kind": row.owner_kind,
        "owner_id": str(row.owner_id),
        "tenant_id": str(row.tenant_id),
        "created_by_user_id": (
            "" if row.created_by_user_id is None else str(row.created_by_user_id)
        ),
        "variant": row.variant,
        "ordinal": row.ordinal,
        "media_type": row.media_type,
        "payload_base64": base64.b64encode(payload).decode("ascii"),
        "sha256_hex": digest.hex(),
        "size_bytes": len(payload),
        "idempotency_key": idempotency_key,
        "request_fingerprint_hex": request_fingerprint.hex(),
    }


def _copy_in_bounded_batches(
    connection: Connection,
    *,
    batch_size: int,
    batch_bytes: int,
) -> None:
    while True:
        candidates = connection.execute(
            _CANDIDATES,
            {
                "batch_size": batch_size,
                "batch_bytes": batch_bytes,
            },
        ).all()
        if not candidates:
            return

        records = [_normalization_record(row) for row in candidates]
        inserted_count = connection.execute(
            _INSERT_BATCH,
            {"batch": json.dumps(records, separators=(",", ":"))},
        ).scalar_one()
        if inserted_count != len(records):
            raise RuntimeError(
                "File/Icon normalization did not attach every copied payload"
            )


def _verify_copied_rows(connection: Connection) -> None:
    mismatch = connection.execute(
        sa.text("""
            WITH expected AS (
                SELECT
                    reference.content_id,
                    CASE
                        WHEN reference.variant = 'transcription'
                            THEN convert_to(file.transcription, 'UTF8')
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
                    'model_input'
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


def upgrade() -> None:
    connection = op.get_bind()
    inline_limit = _positive_setting(
        "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
        _DEFAULT_INLINE_MAXIMUM_BYTES,
    )
    batch_size = _positive_setting(
        "OBJECT_CONTENT_RECONCILIATION_BATCH_SIZE",
        _DEFAULT_BATCH_SIZE,
    )
    _preflight_legacy_rows(connection, inline_limit)

    # Each bounded batch is one atomic statement in autocommit mode. A stopped
    # migration leaves legacy columns authoritative and reruns skip committed
    # references before the final transactional contraction.
    with op.get_context().autocommit_block():
        _copy_in_bounded_batches(
            connection,
            batch_size=batch_size,
            batch_bytes=inline_limit,
        )

    _verify_copied_rows(connection)

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_files_checksum")

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
