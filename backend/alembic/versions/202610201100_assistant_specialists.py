"""Assistant specialists and consultation history.

An assistant may consult other assistants in its space (its specialists)
and answer with one combined reply. The consultations of a question are
kept on the question. Historical questions have no consultation records.

This revision and 202610071400 first followed 202610161000. A database
migrated on that chain reports itself at head, so `alembic upgrade head`
would skip the revisions now before them. Downgrading it drops the
specialists and consultations; to keep them, run with this code:

    alembic stamp --purge 202610161000
    alembic upgrade 202611031206
    alembic stamp 202610201100
    alembic upgrade head

Neither revision changed, so their tables are already in place; the last
step runs whatever revisions follow them.

Revision ID: 202610201100
Revises: 202610071400
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610201100"
down_revision = "202610071400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistants_specialists",
        sa.Column(
            "assistant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "specialist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assistants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assistant_id <> specialist_id", name="ck_assistants_specialists_not_self"
        ),
    )
    op.create_index(
        "ix_assistants_specialists_specialist_id",
        "assistants_specialists",
        ["specialist_id"],
    )
    op.add_column(
        "questions",
        sa.Column("consultations", postgresql.JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "consultations")
    op.drop_index(
        "ix_assistants_specialists_specialist_id", table_name="assistants_specialists"
    )
    op.drop_table("assistants_specialists")
