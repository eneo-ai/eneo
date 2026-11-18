"""retain the approved helper revisions referenced by Skill instructions

Revision ID: 202610291900
Revises: 202610291800
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610291900"
down_revision: str | None = "202610291800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_revision_dependencies",
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("source_revision_id", "target_skill_id"),
        sa.ForeignKeyConstraint(
            ["space_id", "source_skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_skill_dependencies_source_space",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "target_skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_skill_dependencies_target_space",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["source_skill_id", "source_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_skill_dependencies_source_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_skill_id", "target_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_skill_dependencies_target_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "source_skill_id <> target_skill_id",
            name="ck_skill_dependencies_no_self_reference",
        ),
    )
    op.create_index(
        "ix_skill_dependencies_source",
        "skill_revision_dependencies",
        ["source_skill_id"],
    )
    op.create_index(
        "ix_skill_dependencies_target",
        "skill_revision_dependencies",
        ["target_skill_id", "target_revision_id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM skill_revision_dependencies)")
    ):
        raise RuntimeError("Cannot discard approved Skill reference history")
    op.drop_table("skill_revision_dependencies")
