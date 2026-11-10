"""Keep where each part of a streamed recording starts, and every file it is bound to.

A recording cut into parts streams through one live session. The session keeps
the sample at which each part after the first began, and a run binds the
transcript to all the parts' files in recording order, so the text is placed in
the right part and never stands for other audio.

Revision ID: 202611101200
Revises: 202611051000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611101200"
down_revision: str | None = "202611051000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_live_transcripts",
        sa.Column(
            "part_start_samples",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "flow_live_transcripts",
        sa.Column(
            "bound_file_ids",
            sa.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE flow_live_transcripts SET bound_file_ids = ARRAY[bound_file_id] "
        "WHERE bound_file_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_flow_live_transcripts_bound_files",
        "flow_live_transcripts",
        "(bound_file_id IS NULL) = (cardinality(bound_file_ids) = 0) "
        "AND (bound_file_id IS NULL OR bound_file_ids[1] = bound_file_id)",
    )
    op.create_index(
        "ix_flow_live_transcripts_bound_file_ids",
        "flow_live_transcripts",
        ["bound_file_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE flow_live_transcripts IN ACCESS EXCLUSIVE MODE")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM flow_live_transcripts "
                "WHERE cardinality(part_start_samples) > 0 "
                "OR cardinality(bound_file_ids) > 1)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "Refusing to discard where the parts of streamed recordings begin."
        )
    op.drop_index(
        "ix_flow_live_transcripts_bound_file_ids", table_name="flow_live_transcripts"
    )
    op.drop_constraint(
        "ck_flow_live_transcripts_bound_files", "flow_live_transcripts", type_="check"
    )
    op.drop_column("flow_live_transcripts", "bound_file_ids")
    op.drop_column("flow_live_transcripts", "part_start_samples")
