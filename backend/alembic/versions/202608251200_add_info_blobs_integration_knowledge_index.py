"""add index on info_blobs.integration_knowledge_id

`semantic_search` disables sequential scans for the session and filters
chunks through an OR over `info_blobs.group_id` / `website_id` /
`integration_knowledge_id` (see `InfoBlobChunkRepo._filter_on_sources`).
There is no vector index on `info_blob_chunks.embedding`, so the only
efficient plan is to drive the query through a B-tree index on the scope
column and sort just that scope's chunks by distance. `group_id` and
`website_id` have such indexes; `integration_knowledge_id` does not, so
any retrieval touching integration knowledge (SharePoint/Confluence)
falls back to scanning the whole chunk join — cost proportional to the
entire table instead of the selected sources.

`CONCURRENTLY` avoids a write lock on `info_blobs` during the build.

Failure recovery: `CREATE INDEX CONCURRENTLY` can fail mid-build and
leave the index INVALID while Alembic still marks the migration applied.
If integration-knowledge retrieval stays slow after upgrading:

    SELECT indexrelid::regclass, indisvalid
    FROM pg_index
    WHERE indexrelid::regclass::text
        = 'ix_info_blobs_integration_knowledge_id';

    -- if indisvalid = false:
    DROP INDEX CONCURRENTLY IF EXISTS ix_info_blobs_integration_knowledge_id;
    CREATE INDEX CONCURRENTLY ix_info_blobs_integration_knowledge_id
      ON info_blobs (integration_knowledge_id);

Do not re-run the Alembic migration to recover — the IF NOT EXISTS guard
skips the rebuild even when the existing index is INVALID.

Revision ID: 202608251200
Revises: 202608211300
Create Date: 2026-08-25 12:00:00
"""

from alembic import op

revision = "202608251200"
down_revision = "202608211300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                ix_info_blobs_integration_knowledge_id
            ON info_blobs (integration_knowledge_id);
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_info_blobs_integration_knowledge_id;"
        )
