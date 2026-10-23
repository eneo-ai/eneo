"""add sharepoint item info blob index

A SharePoint sync looks up, replaces and deletes a knowledge item's blobs one
file at a time by ``(integration_knowledge_id, sharepoint_item_id)``. With
only ``ix_info_blobs_integration_knowledge_id`` each lookup reads every blob of
the knowledge, superseded versions included, so a full sync of a large
library is quadratic. This index covers the pair.

The predicate keeps blobs from other sources (uploads, websites) out of the
index. It is implied by any ``sharepoint_item_id = $n`` comparison whatever
the parameter's value, so generic plans can use the index too; the deletes
match superseded versions as well, so the index is not limited to active ones.

``CONCURRENTLY`` avoids a write lock on ``info_blobs`` during the build. It
can leave the index INVALID if the build fails. A retry drops that index
before building it again. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indexrelid::regclass::text
        = 'ix_info_blobs_integration_knowledge_sharepoint_item';
    -- if indisvalid = false, run the upgrade statements by hand.

Revision ID: 202610191500
Revises: 202610191400
Create Date: 2026-10-19 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610191500"
down_revision: str | None = "202610191400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_info_blobs_integration_knowledge_sharepoint_item"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "info_blobs",
            ["integration_knowledge_id", "sharepoint_item_id"],
            postgresql_where=sa.text("sharepoint_item_id IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
