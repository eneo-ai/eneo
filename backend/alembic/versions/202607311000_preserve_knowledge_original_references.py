"""preserve exact originals for new knowledge uploads

Revision ID: 202607311000
Revises: 202607301200
Create Date: 2026-07-31 10:00:00.000000

The old reference shape never had a production writer. Upgrade therefore
refuses unexpected rows instead of guessing their meaning. The coordinated
release must also drain executable legacy knowledge jobs before this contract
changes. Pre-durable queued jobs left after the old worker drains have no
durable recovery evidence; the migration records those jobs as interrupted
instead of requiring operators to repair them by hand.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607311000"
down_revision: str | None = "202607301200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "info_blob_content_references"
_PRIMARY_KEY = "pk_info_blob_content_references"
_VARIANT_CHECK = "ck_info_blob_content_references_variant"
_FILENAME_CHECK = "ck_info_blob_content_references_original_filename"
_ACTIVE_KNOWLEDGE_JOB = """
    task IN ('upload_info_blob', 'transcription')
    AND status IN ('queued', 'in progress')
"""
_PRE_DURABLE_QUEUED_JOB = """
    task IN ('upload_info_blob', 'transcription')
    AND status = 'queued'
    AND dispatch_envelope IS NULL
"""
_BLOCKING_KNOWLEDGE_JOB = f"""
    {_ACTIVE_KNOWLEDGE_JOB}
    AND NOT (
        status = 'queued'
        AND dispatch_envelope IS NULL
    )
"""
_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"

logger = logging.getLogger("alembic.runtime.migration")


def _count(statement: str) -> int:
    return int(op.get_bind().execute(sa.text(statement)).scalar_one())


def _retire_pre_durable_queued_jobs() -> int:
    return _count(
        f"""
        WITH retired AS (
            UPDATE jobs
            SET status = 'failed',
                result_location = NULL,
                failure_code = 'processing_interrupted',
                finished_at = now(),
                updated_at = now()
            WHERE {_PRE_DURABLE_QUEUED_JOB}
            RETURNING 1
        )
        SELECT count(*) FROM retired
        """
    )


def _lock_jobs_for_classification() -> None:
    try:
        op.get_bind().exec_driver_sql(
            "LOCK TABLE jobs IN SHARE ROW EXCLUSIVE MODE NOWAIT"
        )
    except sa.exc.DBAPIError as error:
        sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
            error.orig,
            "pgcode",
            None,
        )
        if sqlstate != _LOCK_NOT_AVAILABLE_SQLSTATE:
            raise
        raise RuntimeError(
            "Knowledge-original migration could not lock jobs; stop all API "
            "replicas and old workers, then retry db-init"
        ) from error


def _install_reference_identity_fence(*, include_variant: bool) -> None:
    info_blob_identity = (
        "(NEW.info_blob_id, NEW.content_id, NEW.variant) "
        "IS DISTINCT FROM "
        "(OLD.info_blob_id, OLD.content_id, OLD.variant)"
        if include_variant
        else "(NEW.info_blob_id, NEW.content_id) "
        "IS DISTINCT FROM "
        "(OLD.info_blob_id, OLD.content_id)"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION object_content_reference_identity_fence()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'file_content_references' THEN
                IF (NEW.file_id, NEW.content_id, NEW.variant, NEW.ordinal)
                    IS DISTINCT FROM
                    (OLD.file_id, OLD.content_id, OLD.variant, OLD.ordinal) THEN
                    RAISE EXCEPTION
                        'object content reference identity is immutable';
                END IF;
            ELSIF TG_TABLE_NAME = 'info_blob_content_references' THEN
                IF {info_blob_identity} THEN
                    RAISE EXCEPTION
                        'object content reference identity is immutable';
                END IF;
            ELSIF TG_TABLE_NAME = 'icon_content_references' THEN
                IF (NEW.icon_id, NEW.content_id, NEW.variant)
                    IS DISTINCT FROM
                    (OLD.icon_id, OLD.content_id, OLD.variant) THEN
                    RAISE EXCEPTION
                        'object content reference identity is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    reference_count = _count(f"SELECT count(*) FROM {_TABLE}")
    if reference_count:
        raise RuntimeError(
            "Knowledge-original migration found "
            f"{reference_count} unexpected existing reference row(s); "
            "investigate the drift before upgrading"
        )

    # Serialize with writers without blocking ordinary reads or waiting behind
    # a missed old process indefinitely.
    _lock_jobs_for_classification()

    blocking_job_count = _count(
        f"SELECT count(*) FROM jobs WHERE {_BLOCKING_KNOWLEDGE_JOB}"
    )
    if blocking_job_count:
        raise RuntimeError(
            "Knowledge-original migration found "
            f"{blocking_job_count} active legacy knowledge job(s); "
            "stop API replicas and drain old workers before upgrading"
        )

    retired_job_count = _retire_pre_durable_queued_jobs()

    op.drop_constraint(_PRIMARY_KEY, _TABLE, type_="primary")
    op.drop_constraint(_VARIANT_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "variant")
    op.add_column(
        _TABLE,
        sa.Column("original_filename", sa.String(length=255), nullable=False),
    )
    op.create_check_constraint(
        _FILENAME_CHECK,
        _TABLE,
        "char_length(original_filename) BETWEEN 1 AND 255",
    )
    op.create_primary_key(_PRIMARY_KEY, _TABLE, ["info_blob_id"])
    _install_reference_identity_fence(include_variant=False)

    if retired_job_count:
        logger.info(
            "Retired %d queued legacy knowledge job(s) without a durable "
            "dispatch envelope",
            retired_job_count,
        )


def downgrade() -> None:
    reference_count = _count(f"SELECT count(*) FROM {_TABLE}")
    if reference_count:
        raise RuntimeError(
            "Cannot downgrade while "
            f"{reference_count} knowledge original reference row(s) remain; "
            "recover forward or restore the paired pre-upgrade backup"
        )

    active_v2_job_count = _count(
        f"""
        SELECT count(*)
        FROM jobs
        WHERE {_ACTIVE_KNOWLEDGE_JOB}
          AND dispatch_envelope ->> 'version' = '2'
        """
    )
    if active_v2_job_count:
        raise RuntimeError(
            "Cannot downgrade while "
            f"{active_v2_job_count} active v2 knowledge job(s) remain; "
            "drain the jobs or recover forward"
        )

    op.drop_constraint(_PRIMARY_KEY, _TABLE, type_="primary")
    op.drop_constraint(_FILENAME_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, "original_filename")
    op.add_column(
        _TABLE,
        sa.Column(
            "variant",
            sa.String(length=32),
            nullable=False,
            server_default="extracted_text",
        ),
    )
    op.alter_column(_TABLE, "variant", server_default=None)
    op.create_check_constraint(
        _VARIANT_CHECK,
        _TABLE,
        "variant = 'extracted_text'",
    )
    op.create_primary_key(_PRIMARY_KEY, _TABLE, ["info_blob_id", "variant"])
    _install_reference_identity_fence(include_variant=True)
