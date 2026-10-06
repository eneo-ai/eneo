from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.files_table import Files
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.logging_table import logging_table
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users

if TYPE_CHECKING:
    from eneo.database.tables.mcp_tool_references_table import McpToolReference


class Questions(BasePublic):
    question: Mapped[str] = mapped_column()
    answer: Mapped[str] = mapped_column()
    num_tokens_question: Mapped[int] = mapped_column()
    num_tokens_answer: Mapped[int] = mapped_column()
    context_prompt_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    context_completion_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    skill_context_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    tool_calls: Mapped[Optional[list[object]]] = mapped_column(JSONB, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(nullable=True)
    skill_provenance: Mapped[Optional[list[dict[str, object]]]] = mapped_column(
        JSONB, nullable=True
    )
    skill_activation_data: Mapped[Optional[dict[str, object]]] = mapped_column(
        "skill_activation",
        JSONB,
        nullable=True,
        deferred=True,
        deferred_raiseload=True,
    )

    # Foreign keys
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="RESTRICT"),
    )
    logging_details_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(logging_table.id, ondelete="SET NULL")  # type: ignore[attr-defined]
    )
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), index=True
    )
    service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Services.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL")
    )

    # Relationships
    info_blob_references: Mapped[list["InfoBlobReferences"]] = relationship(
        order_by="[InfoBlobReferences.order, InfoBlobReferences.similarity_score.desc()]",
        viewonly=True,
    )
    logging_details = relationship(logging_table)
    assistant: Mapped[Assistants] = relationship()
    session: Mapped[Sessions] = relationship(viewonly=True)
    completion_model: Mapped[CompletionModels] = relationship()

    info_blobs: AssociationProxy[list[InfoBlobs]] = association_proxy(
        "info_blob_references", "info_blob"
    )
    questions_files: Mapped[list["QuestionsFiles"]] = relationship(
        order_by="QuestionsFiles.file_id"
    )
    mcp_tool_references: Mapped[list["McpToolReference"]] = relationship(
        order_by="[McpToolReference.tool_call_id, McpToolReference.order]"
    )
    # Loaded with every question (one small IN query), so each path that turns
    # rows into Question models carries the rating without its own option.
    feedback: Mapped[Optional["QuestionFeedback"]] = relationship(
        lazy="selectin", viewonly=True
    )

    @property
    def skill_activation(self) -> Optional[dict[str, object]]:
        """Expose activation evidence only when an explicit query loaded it."""
        state = sa_inspect(self)
        assert state is not None
        if "skill_activation_data" in state.unloaded:
            return None
        return self.skill_activation_data


class QuestionFeedback(BasePublic):
    """The conversation owner's rating of one answer, with an optional comment.

    One row per answer: rating again replaces it, clearing deletes it. The
    principal columns record who rated: the owning user, or the service API
    key that owns the conversation. Independent of the conversation-level
    rating on ``sessions.feedback_value``.
    """

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey(Questions.id, ondelete="CASCADE")
    )
    value: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True
    )
    api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ApiKeysV2.id, ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("question_id", name="uq_question_feedback_question_id"),
        CheckConstraint("value IN (-1, 1)", name="ck_question_feedback_value"),
    )


class InfoBlobReferences(BaseCrossReference):
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey(Questions.id, ondelete="CASCADE"),
        primary_key=True,
    )
    info_blob_id: Mapped[str] = mapped_column(
        ForeignKey(InfoBlobs.id, ondelete="CASCADE"), primary_key=True
    )
    similarity_score: Mapped[Optional[float]] = mapped_column()
    order: Mapped[Optional[int]] = mapped_column()
    info_blob: Mapped[InfoBlobs] = relationship()


class QuestionsFiles(BaseCrossReference):
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey(Questions.id, ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[str] = mapped_column()

    file: Mapped[Files] = relationship()

    __table_args__ = (Index("ix_questions_files_file_id", "file_id"),)
