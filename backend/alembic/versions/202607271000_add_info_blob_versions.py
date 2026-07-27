"""preserve complete InfoBlob versions during replacement

Revision ID: 202607271000
Revises: 202607262200

Downgrade is lossless only before a replacement creates history. Once a source
has a superseded row or more than one version, recover forward or restore a
matching pre-upgrade database backup rather than discarding versions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607271000"
down_revision: str | tuple[str, str] | None = "202607262200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "info_blobs"
_BACKFILL_BATCH_SIZE = 1_000
_STATE_CONSTRAINT = "ck_info_blobs_version_state"
_SOURCE_NOT_NULL = "ck_info_blobs_source_id_not_null"
_STATE_NOT_NULL = "ck_info_blobs_version_state_not_null"
_ACTIVE_SOURCE_INDEX = "uq_info_blobs_active_source"
_SOURCE_INDEX = "ix_info_blobs_source_id"


def _backfill_versions() -> None:
    bind = op.get_bind()
    while True:
        result = bind.execute(
            sa.text(
                f"""
                WITH batch AS (
                    SELECT ctid
                    FROM {_TABLE}
                    WHERE source_id IS NULL OR version_state IS NULL
                    ORDER BY ctid
                    LIMIT :batch_size
                    FOR UPDATE
                )
                UPDATE {_TABLE} AS info_blob
                SET source_id = COALESCE(info_blob.source_id, info_blob.id),
                    version_state = COALESCE(info_blob.version_state, 'active')
                FROM batch
                WHERE info_blob.ctid = batch.ctid
                """
            ),
            {"batch_size": _BACKFILL_BATCH_SIZE},
        )
        if result.rowcount < _BACKFILL_BATCH_SIZE:
            break

    remaining = bind.execute(
        sa.text(
            f"""
            SELECT count(*)
            FROM {_TABLE}
            WHERE source_id IS NULL OR version_state IS NULL
            """
        )
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"InfoBlob version backfill left {remaining} rows incomplete"
        )


def _create_indexes() -> None:
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ACTIVE_SOURCE_INDEX}")
    op.execute(
        f"""
        CREATE UNIQUE INDEX CONCURRENTLY {_ACTIVE_SOURCE_INDEX}
        ON {_TABLE} (source_id)
        WHERE version_state = 'active'
        """
    )
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_SOURCE_INDEX}")
    op.execute(f"CREATE INDEX CONCURRENTLY {_SOURCE_INDEX} ON {_TABLE} (source_id)")


def upgrade() -> None:
    # Deployments stop backend and worker writers for this producer-sensitive
    # migration. Autocommit keeps each bounded backfill/index phase restartable
    # and prevents a table-wide transaction from retaining row locks.
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            ALTER TABLE {_TABLE}
                ADD COLUMN IF NOT EXISTS source_id UUID,
                ADD COLUMN IF NOT EXISTS version_state VARCHAR(16)
            """
        )
        _backfill_versions()
        op.execute(
            f"""
            ALTER TABLE {_TABLE}
                DROP CONSTRAINT IF EXISTS {_STATE_CONSTRAINT},
                DROP CONSTRAINT IF EXISTS {_SOURCE_NOT_NULL},
                DROP CONSTRAINT IF EXISTS {_STATE_NOT_NULL},
                ADD CONSTRAINT {_STATE_CONSTRAINT}
                    CHECK (version_state IN ('active', 'superseded')) NOT VALID,
                ADD CONSTRAINT {_SOURCE_NOT_NULL}
                    CHECK (source_id IS NOT NULL) NOT VALID,
                ADD CONSTRAINT {_STATE_NOT_NULL}
                    CHECK (version_state IS NOT NULL) NOT VALID
            """
        )
        for constraint in (
            _STATE_CONSTRAINT,
            _SOURCE_NOT_NULL,
            _STATE_NOT_NULL,
        ):
            op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {constraint}")
        op.execute(
            f"""
            ALTER TABLE {_TABLE}
                ALTER COLUMN source_id SET NOT NULL,
                ALTER COLUMN version_state SET NOT NULL,
                DROP CONSTRAINT {_SOURCE_NOT_NULL},
                DROP CONSTRAINT {_STATE_NOT_NULL}
            """
        )
        _create_indexes()


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM {_TABLE}
                    WHERE version_state <> 'active'
                ) OR EXISTS (
                    SELECT source_id
                    FROM {_TABLE}
                    GROUP BY source_id
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'cannot remove InfoBlob version history; recover forward or restore a matching backup'
                        USING ERRCODE = '23514';
                END IF;
            END;
            $$
            """
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_SOURCE_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_ACTIVE_SOURCE_INDEX}")
        op.execute(
            f"""
            ALTER TABLE {_TABLE}
                DROP CONSTRAINT IF EXISTS {_STATE_CONSTRAINT},
                DROP COLUMN IF EXISTS version_state,
                DROP COLUMN IF EXISTS source_id
            """
        )
