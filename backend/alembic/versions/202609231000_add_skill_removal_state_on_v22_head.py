"""Retain removed Skills and their immutable revisions.

Parented on the v2.2 head so release/v2.2 can ship the identical file. The
develop-only migrations after 202609101000 then stay unapplied on a v2.2
database, and 202609231001 runs them on the way to the next release. Develop
databases that already ran 202609181000 have this schema, so upgrade skips.

Revision ID: 202609231000
Revises: 202609101000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609231000"
down_revision = "202609101000"
branch_labels = None
depends_on = None


def _has_removed_at() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("skills")
    return any(column["name"] == "removed_at" for column in columns)


def upgrade() -> None:
    if _has_removed_at():
        return
    op.add_column(
        "skills", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_skills_removed_inactive",
        "skills",
        "removed_at IS NULL OR NOT is_active",
    )
    op.drop_constraint("uq_skills_space_id_slug", "skills", type_="unique")
    op.create_index(
        "uq_skills_space_id_slug",
        "skills",
        ["space_id", "slug"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    if not _has_removed_at():
        return
    # Keep a removal from committing between the history check and dropping its state.
    op.execute("LOCK TABLE skills IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM skills WHERE removed_at IS NOT NULL)")
    ):
        raise RuntimeError(
            "Cannot discard Skill removal history. Retain this migration while removed Skills exist."
        )
    op.drop_constraint("ck_skills_removed_inactive", "skills", type_="check")
    op.drop_index("uq_skills_space_id_slug", table_name="skills")
    op.create_unique_constraint(
        "uq_skills_space_id_slug", "skills", ["space_id", "slug"]
    )
    op.drop_column("skills", "removed_at")
