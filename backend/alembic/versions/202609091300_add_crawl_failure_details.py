"""Retain failed crawl addresses and the latest completed indexing time.

Revision ID: 202609091300
Revises: 202609091230
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609091300"
down_revision = "202609091230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("websites", sa.Column("last_indexed_at", sa.TIMESTAMP(timezone=True)))
    op.add_column(
        "crawl_runs",
        sa.Column(
            "failure_details_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "crawl_run_failures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "crawl_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.CheckConstraint(
            "kind IN ('page', 'file')", name="ck_crawl_run_failures_kind"
        ),
    )
    # This table is new and empty; the index can be built in the same transaction.
    op.create_index(
        "ix_crawl_run_failures_run_created",
        "crawl_run_failures",
        ["crawl_run_id", "created_at", "id"],
    )
    op.execute("""
        UPDATE websites AS website
        SET last_indexed_at = completed.finished_at
        FROM (
            SELECT website_id, max(finished_at) AS finished_at
            FROM crawl_runs
            WHERE phase = 'terminal'
              AND outcome IN ('succeeded', 'unchanged', 'empty', 'partial')
              AND finished_at IS NOT NULL
            GROUP BY website_id
        ) AS completed
        WHERE website.id = completed.website_id
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM crawl_run_failures) THEN
                RAISE EXCEPTION 'Cannot downgrade while recorded crawl failure addresses exist; export and explicitly remove them first';
            END IF;
        END $$;
    """)
    op.drop_table("crawl_run_failures")
    op.drop_column("crawl_runs", "failure_details_available")
    op.drop_column("websites", "last_indexed_at")
