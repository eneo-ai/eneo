"""create versioned skills, bindings, and execution provenance

Revision ID: 202607151200
Revises: 202607151100
Create Date: 2026-07-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607151200"
down_revision: str | None = "202607151100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "current_revision_number",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "current_revision_number >= 1",
            name="ck_skills_current_revision_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "space_id",
            "id",
            name="uq_skills_space_id_id",
        ),
        sa.UniqueConstraint(
            "space_id",
            "slug",
            name="uq_skills_space_id_slug",
        ),
    )

    op.create_table(
        "skill_revisions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_skill_revisions_revision_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_skill_revisions_created_by_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name="fk_skill_revisions_skill_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id",
            "id",
            name="uq_skill_revisions_skill_id_id",
        ),
        sa.UniqueConstraint(
            "skill_id",
            "revision_number",
            name="uq_skill_revisions_skill_id_revision_number",
        ),
    )

    op.create_foreign_key(
        "fk_skills_current_revision",
        "skills",
        "skill_revisions",
        ["id", "current_revision_number"],
        ["skill_id", "revision_number"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "assistant_skill_bindings",
        sa.Column("assistant_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("skill_revision_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_assistant_skill_bindings_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "assistant_id"],
            ["assistants.space_id", "assistants.id"],
            name="fk_assistant_skill_bindings_assistant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_assistant_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_assistant_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint(
            "assistant_id",
            "skill_id",
            name="pk_assistant_skill_bindings",
        ),
        sa.UniqueConstraint(
            "assistant_id",
            "position",
            name="uq_assistant_skill_bindings_assistant_id_position",
        ),
    )
    op.create_index(
        "ix_assistant_skill_bindings_skill_id",
        "assistant_skill_bindings",
        ["skill_id"],
    )

    op.create_table(
        "app_skill_bindings",
        sa.Column("app_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("skill_revision_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_app_skill_bindings_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "app_id"],
            ["apps.space_id", "apps.id"],
            name="fk_app_skill_bindings_app",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_app_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_app_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint(
            "app_id",
            "skill_id",
            name="pk_app_skill_bindings",
        ),
        sa.UniqueConstraint(
            "app_id",
            "position",
            name="uq_app_skill_bindings_app_id_position",
        ),
    )
    op.create_index(
        "ix_app_skill_bindings_skill_id",
        "app_skill_bindings",
        ["skill_id"],
    )

    op.create_table(
        "governance_policy_skill_bindings",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("skill_space_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("skill_revision_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_governance_policy_skill_bindings_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["governance_policies.tenant_id", "governance_policies.id"],
            name="fk_governance_policy_skill_bindings_policy",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_governance_policy_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_governance_policy_skill_bindings_space",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_governance_policy_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint(
            "policy_id",
            "skill_id",
            name="pk_governance_policy_skill_bindings",
        ),
        sa.UniqueConstraint(
            "policy_id",
            "position",
            name="uq_governance_policy_skill_bindings_policy_id_position",
        ),
    )
    op.create_index(
        "ix_governance_policy_skill_bindings_skill_id",
        "governance_policy_skill_bindings",
        ["skill_id"],
    )
    op.create_index(
        "ix_governance_policy_skill_bindings_tenant_space",
        "governance_policy_skill_bindings",
        ["tenant_id", "skill_space_id"],
    )

    op.add_column(
        "questions",
        sa.Column(
            "skill_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "app_runs",
        sa.Column(
            "skill_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_app_runs_skill_provenance_gin",
        "app_runs",
        ["skill_provenance"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"skill_provenance": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_app_runs_skill_provenance_gin", table_name="app_runs")
    op.drop_column("app_runs", "skill_provenance")
    op.drop_column("questions", "skill_provenance")
    op.drop_index(
        "ix_governance_policy_skill_bindings_tenant_space",
        table_name="governance_policy_skill_bindings",
    )
    op.drop_index(
        "ix_governance_policy_skill_bindings_skill_id",
        table_name="governance_policy_skill_bindings",
    )
    op.drop_table("governance_policy_skill_bindings")
    op.drop_index(
        "ix_app_skill_bindings_skill_id",
        table_name="app_skill_bindings",
    )
    op.drop_table("app_skill_bindings")
    op.drop_index(
        "ix_assistant_skill_bindings_skill_id",
        table_name="assistant_skill_bindings",
    )
    op.drop_table("assistant_skill_bindings")
    op.drop_constraint(
        "fk_skills_current_revision",
        "skills",
        type_="foreignkey",
    )
    op.drop_table("skill_revisions")
    op.drop_table("skills")
