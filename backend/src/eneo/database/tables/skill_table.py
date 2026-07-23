from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users


class Skills(BasePublic):
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(server_default="true")
    current_revision_number: Mapped[int] = mapped_column(server_default="1")
    published_revision_number: Mapped[int | None] = mapped_column(nullable=True)
    first_published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT")
    )

    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "slug",
            name="uq_skills_space_id_slug",
        ),
        UniqueConstraint(
            "space_id",
            "id",
            name="uq_skills_space_id_id",
        ),
        CheckConstraint(
            "current_revision_number >= 1",
            name="ck_skills_current_revision_number_positive",
        ),
        CheckConstraint(
            ("published_revision_number IS NULL OR first_published_at IS NOT NULL"),
            name="ck_skills_published_requires_first_published_at",
        ),
        CheckConstraint(
            "published_revision_number IS NULL OR is_active",
            name="ck_skills_published_active",
        ),
        ForeignKeyConstraint(
            ["id", "current_revision_number"],
            ["skill_revisions.skill_id", "skill_revisions.revision_number"],
            name="fk_skills_current_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id", "published_revision_number"],
            ["skill_revisions.skill_id", "skill_revisions.revision_number"],
            name="fk_skills_published_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )


class SkillRevisions(BasePublic):
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Skills.id,
            name="fk_skill_revisions_skill_id",
            ondelete="CASCADE",
        )
    )
    revision_number: Mapped[int] = mapped_column()
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1024))
    instructions: Mapped[str] = mapped_column(Text)
    content_digest: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Users.id,
            name="fk_skill_revisions_created_by_user_id",
            ondelete="RESTRICT",
        )
    )

    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "revision_number",
            name="uq_skill_revisions_skill_id_revision_number",
        ),
        UniqueConstraint(
            "skill_id",
            "id",
            name="uq_skill_revisions_skill_id_id",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_skill_revisions_revision_number_positive",
        ),
    )


class SkillExecutionBlocks(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column()
    skill_space_id: Mapped[UUID] = mapped_column()
    skill_id: Mapped[UUID] = mapped_column()
    blocked_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Users.id,
            name="fk_skill_execution_blocks_blocked_by_user_id",
            ondelete="RESTRICT",
        )
    )
    reason: Mapped[str] = mapped_column(Text)
    unblocked_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            Users.id,
            name="fk_skill_execution_blocks_unblocked_by_user_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    unblock_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    unblocked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_skill_execution_blocks_tenant_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_skill_execution_blocks_skill",
            ondelete="NO ACTION",
        ),
        CheckConstraint(
            "char_length(btrim(reason)) BETWEEN 1 AND 1000",
            name="ck_skill_execution_blocks_reason_length",
        ),
        CheckConstraint(
            """
            (
                unblocked_at IS NULL
                AND unblocked_by_user_id IS NULL
                AND unblock_reason IS NULL
            )
            OR
            (
                unblocked_at IS NOT NULL
                AND unblocked_by_user_id IS NOT NULL
                AND char_length(btrim(unblock_reason)) BETWEEN 1 AND 1000
            )
            """,
            name="ck_skill_execution_blocks_unblock_state",
        ),
        Index(
            "uq_skill_execution_blocks_active_tenant_skill",
            "tenant_id",
            "skill_id",
            unique=True,
            postgresql_where=text("unblocked_at IS NULL"),
        ),
        Index(
            "ix_skill_execution_blocks_tenant_skill_created",
            "tenant_id",
            "skill_id",
            "created_at",
        ),
    )


class AssistantSkillBindings(BaseCrossReference):
    assistant_id: Mapped[UUID] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column()
    space_id: Mapped[UUID] = mapped_column()
    skill_space_id: Mapped[UUID] = mapped_column()
    skill_id: Mapped[UUID] = mapped_column()
    skill_revision_id: Mapped[UUID] = mapped_column()
    position: Mapped[int] = mapped_column()

    __table_args__ = (
        PrimaryKeyConstraint(
            "assistant_id",
            "skill_id",
            name="pk_assistant_skill_bindings",
        ),
        UniqueConstraint(
            "assistant_id",
            "position",
            name="uq_assistant_skill_bindings_assistant_id_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_assistant_skill_bindings_position_nonnegative",
        ),
        ForeignKeyConstraint(
            ["space_id", "assistant_id"],
            ["assistants.space_id", "assistants.id"],
            name="fk_assistant_skill_bindings_assistant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_assistant_skill_bindings_parent_space",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_assistant_skill_bindings_skill_space",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_assistant_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_assistant_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_assistant_skill_bindings_skill_id_assistant_id",
            "skill_id",
            "assistant_id",
        ),
        Index(
            "ix_assistant_skill_bindings_tenant_skill_space",
            "tenant_id",
            "skill_space_id",
        ),
    )


class AppSkillBindings(BaseCrossReference):
    app_id: Mapped[UUID] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column()
    space_id: Mapped[UUID] = mapped_column()
    skill_space_id: Mapped[UUID] = mapped_column()
    skill_id: Mapped[UUID] = mapped_column()
    skill_revision_id: Mapped[UUID] = mapped_column()
    position: Mapped[int] = mapped_column()

    __table_args__ = (
        PrimaryKeyConstraint(
            "app_id",
            "skill_id",
            name="pk_app_skill_bindings",
        ),
        UniqueConstraint(
            "app_id",
            "position",
            name="uq_app_skill_bindings_app_id_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_app_skill_bindings_position_nonnegative",
        ),
        ForeignKeyConstraint(
            ["space_id", "app_id"],
            ["apps.space_id", "apps.id"],
            name="fk_app_skill_bindings_app",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_app_skill_bindings_parent_space",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_app_skill_bindings_skill_space",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_app_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_app_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_app_skill_bindings_skill_id_app_id",
            "skill_id",
            "app_id",
        ),
        Index(
            "ix_app_skill_bindings_tenant_skill_space",
            "tenant_id",
            "skill_space_id",
        ),
    )


class GovernancePolicySkillBindings(BaseCrossReference):
    policy_id: Mapped[UUID] = mapped_column()
    tenant_id: Mapped[UUID] = mapped_column()
    skill_space_id: Mapped[UUID] = mapped_column()
    skill_id: Mapped[UUID] = mapped_column()
    skill_revision_id: Mapped[UUID] = mapped_column()
    position: Mapped[int] = mapped_column()

    __table_args__ = (
        PrimaryKeyConstraint(
            "policy_id",
            "skill_id",
            name="pk_governance_policy_skill_bindings",
        ),
        UniqueConstraint(
            "policy_id",
            "position",
            name="uq_governance_policy_skill_bindings_policy_id_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_governance_policy_skill_bindings_position_nonnegative",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "policy_id"],
            ["governance_policies.tenant_id", "governance_policies.id"],
            name="fk_governance_policy_skill_bindings_policy",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "skill_space_id"],
            ["spaces.tenant_id", "spaces.id"],
            name="fk_governance_policy_skill_bindings_space",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_space_id", "skill_id"],
            ["skills.space_id", "skills.id"],
            name="fk_governance_policy_skill_bindings_skill",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["skill_id", "skill_revision_id"],
            ["skill_revisions.skill_id", "skill_revisions.id"],
            name="fk_governance_policy_skill_bindings_revision",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_governance_policy_skill_bindings_skill_id",
            "skill_id",
        ),
        Index(
            "ix_governance_policy_skill_bindings_tenant_space",
            "tenant_id",
            "skill_space_id",
        ),
    )
