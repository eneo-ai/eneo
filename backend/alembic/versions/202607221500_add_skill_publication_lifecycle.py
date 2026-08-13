"""add governed Skill publication lifecycle

Revision ID: 202607221500
Revises: 202607221400
Create Date: 2026-07-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607221500"
down_revision: str | None = "202607221400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("published_revision_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column(
            "first_published_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_skills_published_requires_first_published_at",
        "skills",
        ("published_revision_number IS NULL OR first_published_at IS NOT NULL"),
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        "ck_skills_published_active",
        "skills",
        "published_revision_number IS NULL OR is_active",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        "fk_skills_published_revision",
        "skills",
        "skill_revisions",
        ["id", "published_revision_number"],
        ["skill_id", "revision_number"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
        postgresql_not_valid=True,
    )

    op.execute(
        "ALTER TABLE skills VALIDATE CONSTRAINT "
        "ck_skills_published_requires_first_published_at"
    )
    op.execute("ALTER TABLE skills VALIDATE CONSTRAINT ck_skills_published_active")
    op.execute("ALTER TABLE skills VALIDATE CONSTRAINT fk_skills_published_revision")


def downgrade() -> None:
    op.drop_constraint(
        "fk_skills_published_revision",
        "skills",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_skills_published_active",
        "skills",
        type_="check",
    )
    op.drop_constraint(
        "ck_skills_published_requires_first_published_at",
        "skills",
        type_="check",
    )
    op.drop_column("skills", "first_published_at")
    op.drop_column("skills", "published_revision_number")
