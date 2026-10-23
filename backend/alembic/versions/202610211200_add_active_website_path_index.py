"""add active website path index

Website content is browsed by URL directory: a directory's folder listing and
its page of resources both filter a website's active rows to those whose
navigation path starts with the directory. The path is an expression (query and
fragment removed, a bare origin given its slash), so without this index every
call reads all active rows of the website. This index orders each website's
active paths byte by byte, which turns a directory into a range scan.

The expression must stay identical to ``website_navigation_path()`` in
``eneo.database.tables.info_blobs_table``: the planner uses an expression index
only for the same expression. It is frozen here, as migrations must not change
with application code.

``CONCURRENTLY`` avoids a write lock on ``info_blobs`` during the build. It
can leave the index INVALID if the build fails. A retry drops that index
before building it again. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indexrelid::regclass::text = 'ix_info_blobs_active_website_path';
    -- if indisvalid = false, run the upgrade statements by hand.

Revision ID: 202610211200
Revises: 202610191600
Create Date: 2026-10-21 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202610211200"
down_revision: str | None = "202610191600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_info_blobs_active_website_path"
_ADDRESS = "split_part(split_part(coalesce(website_source_url, url), '?', 1), '#', 1)"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_INDEX} ON info_blobs (
                website_id,
                (CASE WHEN {_ADDRESS} ~ '^https?://[^/]+$'
                    THEN {_ADDRESS} || '/'
                    ELSE {_ADDRESS}
                END) COLLATE "C"
            )
            WHERE version_state = 'active'
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
