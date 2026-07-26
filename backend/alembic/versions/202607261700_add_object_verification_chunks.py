"""persist bounded object range verification chunks

Revision ID: 202607261700
Revises: 202607261000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607261700"
down_revision: str | None = "202607261000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "object_store_objects"
_CHUNK_SIZE = "verification_chunk_size_bytes"
_CHUNK_SHA256 = "verification_chunk_sha256"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_CHUNK_SIZE, sa.BigInteger(), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column(_CHUNK_SHA256, sa.LargeBinary(), nullable=True),
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ALTER COLUMN {_CHUNK_SHA256} SET STORAGE EXTERNAL"
    )

    # Existing descriptors keep today's whole-object verification semantics.
    # Batching bounds row locks and WAL pressure if an operator already has a
    # large pre-production object-content inventory.
    op.execute(f"""
        DO $$
        DECLARE
            updated_rows integer;
        BEGIN
            LOOP
                WITH batch AS (
                    SELECT descriptor.ctid, content.size_bytes, content.sha256
                    FROM {_TABLE} AS descriptor
                    JOIN object_contents AS content
                      ON content.id = descriptor.content_id
                    WHERE descriptor.{_CHUNK_SIZE} IS NULL
                       OR descriptor.{_CHUNK_SHA256} IS NULL
                    ORDER BY descriptor.content_id
                    LIMIT 1000
                    FOR UPDATE OF descriptor SKIP LOCKED
                )
                UPDATE {_TABLE} AS descriptor
                SET {_CHUNK_SIZE} = GREATEST(batch.size_bytes, 1),
                    {_CHUNK_SHA256} = batch.sha256
                FROM batch
                WHERE descriptor.ctid = batch.ctid;

                GET DIAGNOSTICS updated_rows = ROW_COUNT;
                EXIT WHEN updated_rows = 0;
            END LOOP;
        END;
        $$
    """)
    # The descriptor update fires the existing deferred ownership audit. Run
    # it before ALTER TABLE so PostgreSQL has no pending trigger events.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    op.execute(f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_object_store_objects_verification_chunk_size
        CHECK ({_CHUNK_SIZE} IS NOT NULL AND {_CHUNK_SIZE} > 0)
        NOT VALID
    """)
    op.execute(f"""
        ALTER TABLE {_TABLE}
        ADD CONSTRAINT ck_object_store_objects_verification_chunk_sha256
        CHECK (
            {_CHUNK_SHA256} IS NOT NULL
            AND octet_length({_CHUNK_SHA256}) BETWEEN 32 AND 320000
            AND octet_length({_CHUNK_SHA256}) % 32 = 0
        )
        NOT VALID
    """)
    op.execute(f"""
        ALTER TABLE {_TABLE}
        VALIDATE CONSTRAINT ck_object_store_objects_verification_chunk_size
    """)
    op.execute(f"""
        ALTER TABLE {_TABLE}
        VALIDATE CONSTRAINT ck_object_store_objects_verification_chunk_sha256
    """)
    op.alter_column(_TABLE, _CHUNK_SIZE, nullable=False)
    op.alter_column(_TABLE, _CHUNK_SHA256, nullable=False)


def downgrade() -> None:
    # Canonical object SHA-256 remains in object_contents, so rollback safely
    # restores whole-object verification for full and ranged reads.
    op.drop_constraint(
        "ck_object_store_objects_verification_chunk_sha256",
        _TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck_object_store_objects_verification_chunk_size",
        _TABLE,
        type_="check",
    )
    op.drop_column(_TABLE, _CHUNK_SHA256)
    op.drop_column(_TABLE, _CHUNK_SIZE)
