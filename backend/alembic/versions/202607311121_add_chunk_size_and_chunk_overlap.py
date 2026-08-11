"""add chunk_size and chunk_overlap to knowledge sources and info blobs

The knowledge source tables carry the configuration a user asked for. ``info_blobs``
carries the effective values the stored material was actually chunked with, which is
what lets a re-crawl tell whether existing material is stale. NULL on an info blob
means "chunked before this column existed" and deliberately never counts as a
mismatch, so upgrading cannot trigger a mass re-index.

A partial index makes the SharePoint delta's drift check source-scoped. That check
runs on every webhook delta, and ``info_blobs.integration_knowledge_id`` carries only
a foreign key, so without this the common no-drift case has to prove the absence of a
differing row across all active blobs.

Revision ID: 202607311121
Revises: 202608101300
Create Date: 2026-07-31 11:21:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607311121"
down_revision: str | None = "202608101300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "ix_info_blobs_integration_knowledge_chunking"


def upgrade() -> None:
    # Every step here is idempotent, because this revision cannot be stamped
    # atomically. Entering the autocommit block below commits the column additions so
    # CREATE INDEX CONCURRENTLY can run outside a transaction, but Alembic records the
    # revision only once upgrade() returns. A failed index build therefore leaves the
    # columns in place with the revision unrecorded, and a plain ADD COLUMN would make
    # the retry die on a duplicate instead of finishing the job.
    for table in ("groups", "websites", "integration_knowledge"):
        for column in ("chunk_size", "chunk_overlap"):
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} INTEGER")

    # Effective values the stored chunks were produced with. Nullable and left
    # unbackfilled: pre-existing blobs were chunked with unknown settings, and
    # guessing would make the stale check re-index them all on the next crawl.
    for column in ("chunk_size", "chunk_overlap"):
        op.execute(f"ALTER TABLE info_blobs ADD COLUMN IF NOT EXISTS {column} INTEGER")

    # CONCURRENTLY cannot run inside a transaction, so this uses Alembic's autocommit
    # block like the other production indexes in this directory. The predicates mirror
    # the drift query exactly, and the stamp pair is carried so the comparison is
    # answered from the index rather than from heap rows.
    with op.get_context().autocommit_block():
        # A failed concurrent build leaves an invalid index of the same name behind.
        # IF NOT EXISTS would then accept that carcass on retry and quietly return the
        # per-delta drift query to a table scan, so drop it first. Only an invalid one:
        # a valid index means the build already succeeded.
        connection = op.get_bind()
        invalid = connection.exec_driver_sql(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            f"WHERE c.relname = '{INDEX_NAME}' AND NOT i.indisvalid"
        ).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")

        op.execute(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                {INDEX_NAME}
            ON info_blobs (integration_knowledge_id, chunk_size, chunk_overlap)
            WHERE version_state = 'active'
              AND integration_knowledge_id IS NOT NULL
              AND chunk_size IS NOT NULL
              AND chunk_overlap IS NOT NULL;
        """)


def downgrade() -> None:
    # Idempotent for the same reason the upgrade is: the revision is unstamped only
    # after downgrade() returns, so a failure after the index drop must be retryable.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")

    for column in ("chunk_overlap", "chunk_size"):
        op.execute(f"ALTER TABLE info_blobs DROP COLUMN IF EXISTS {column}")

    for table in ("groups", "websites", "integration_knowledge"):
        for column in ("chunk_overlap", "chunk_size"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
