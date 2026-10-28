"""add active integration knowledge info blob index

Every space lookup served to the UI counts the active info_blobs of each
integration knowledge item, and so does every service that loads a space to
authorize a request (``active_document_counts``). The existing
``ix_info_blobs_integration_knowledge_id`` covers the id alone, so the
``version_state = 'active'`` filter is checked on the heap for every
superseded version too. This partial index holds only active rows, so the
count is an index-only scan.

``CONCURRENTLY`` avoids a write lock on ``info_blobs`` during the build. It
can leave the index INVALID if the build fails. A retry drops that index
before building it again. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indexrelid::regclass::text
        = 'ix_info_blobs_active_integration_knowledge';
    -- if indisvalid = false, run the upgrade statements by hand.

Revision ID: 202610191030
Revises: 202610131400
Create Date: 2026-10-19 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610191030"
down_revision: str | None = "202610131400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_info_blobs_active_integration_knowledge"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "info_blobs",
            ["integration_knowledge_id"],
            postgresql_where=sa.text("version_state = 'active'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
