"""Create content_derivations, the edges from copy sessions to their sources.

Revision ID: 202611081500
Revises: 202610071400
A new, empty table with ids only and no foreign keys; no existing data changes.
Downgrade drops it, so copies made before the downgrade are no longer known as
copies and stay readable after a source is removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611081500"
down_revision: str = "202610071400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_derivations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("copy_session_id", sa.Uuid(), nullable=False),
        sa.Column("source_question_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "copy_session_id",
            "source_question_id",
            name="uq_content_derivations_copy_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("content_derivations")
