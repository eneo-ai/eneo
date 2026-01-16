from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.ai_models_table import CompletionModels, TranscriptionModels
from intric.database.tables.app_template_table import AppTemplates
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.files_table import Files
from intric.database.tables.icons_table import Icons
from intric.database.tables.job_table import Jobs
from intric.database.tables.prompts_table import Prompts
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class Apps(BasePublic):
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    completion_model_kwargs: Mapped[Optional[dict]] = mapped_column(JSONB)
    published: Mapped[bool] = mapped_column()
    data_retention_days: Mapped[Optional[int]] = mapped_column()

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="SET NULL"))
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    template_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(AppTemplates.id, ondelete="SET NULL")
    )
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL")
    )
    transcription_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(TranscriptionModels.id, ondelete="SET NULL")
    )
    icon_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Icons.id, ondelete="SET NULL"), nullable=True
    )

    # Relationships
    completion_model: Mapped[Optional[CompletionModels]] = relationship()
    transcription_model: Mapped[Optional[TranscriptionModels]] = relationship()
    input_fields: Mapped[list["InputFields"]] = relationship(
        order_by="InputFields.created_at", viewonly=True
    )
    attachments: Mapped[list["AppsFiles"]] = relationship(
        order_by="AppsFiles.created_at", viewonly=True
    )
    template: Mapped[Optional[AppTemplates]] = relationship(viewonly=True)


class AppRuns(BasePublic):
    input_text: Mapped[Optional[str]] = mapped_column()
    output_text: Mapped[Optional[str]] = mapped_column()
    num_tokens_input: Mapped[Optional[int]] = mapped_column()
    num_tokens_output: Mapped[Optional[int]] = mapped_column()

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="SET NULL"))
    app_id: Mapped[UUID] = mapped_column(ForeignKey(Apps.id, ondelete="CASCADE"))
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL")
    )
    completion_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL")
    )

    # Relationships
    input_files: Mapped[list["AppRunsFiles"]] = relationship(viewonly=True)
    user: Mapped[Users] = relationship()
    job: Mapped[Jobs] = relationship()


class InputFields(BasePublic):
    type: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="SET NULL"))
    app_id: Mapped[UUID] = mapped_column(ForeignKey(Apps.id, ondelete="CASCADE"))


class AppsFiles(BaseCrossReference):
    app_id: Mapped[UUID] = mapped_column(
        ForeignKey(Apps.id, ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    file: Mapped[Files] = relationship()


class AppsPrompts(BaseCrossReference):
    prompt_id: Mapped[UUID] = mapped_column(
        ForeignKey(Prompts.id, ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[UUID] = mapped_column(
        ForeignKey(Apps.id, ondelete="CASCADE"), primary_key=True
    )
    is_selected: Mapped[bool] = mapped_column()


class AppRunsFiles(BaseCrossReference):
    app_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(AppRuns.id, ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    file: Mapped[Files] = relationship()
