from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.ai_models_table import (
    CompletionModels,
    EmbeddingModels,
    TranscriptionModels,
)
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.security_classifications_table import SecurityClassification
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users

if TYPE_CHECKING:
    from intric.database.tables.app_table import Apps
    from intric.database.tables.assistant_table import Assistants
    from intric.database.tables.collections_table import CollectionsTable
    from intric.database.tables.integration_table import IntegrationKnowledge
    from intric.database.tables.service_table import Services
    from intric.database.tables.websites_table import Websites


class Spaces(BasePublic):
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    data_retention_days: Mapped[Optional[int]] = mapped_column()

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), unique=True
    )
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassification.id, ondelete="SET NULL"), nullable=True
    )

    tenant_space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True, index=True
    )

    tenant_space: Mapped[Optional["Spaces"]] = relationship(
        "Spaces",
        foreign_keys="Spaces.tenant_space_id",
        remote_side="Spaces.id",
        viewonly=True,
    )

    # Relationships
    security_classification: Mapped[Optional["SecurityClassification"]] = relationship(
        back_populates="spaces"
    )
    embedding_models: Mapped[list[EmbeddingModels]] = relationship(
        secondary="spaces_embedding_models", order_by=EmbeddingModels.created_at
    )
    completion_models: Mapped[list[CompletionModels]] = relationship(
        secondary="spaces_completion_models", order_by=CompletionModels.created_at
    )
    transcription_models: Mapped[list[TranscriptionModels]] = relationship(
        secondary="spaces_transcription_models", order_by=TranscriptionModels.created_at
    )
    members: Mapped[list["SpacesUsers"]] = relationship(
        order_by="SpacesUsers.created_at", viewonly=True
    )
    collections: Mapped[list["CollectionsTable"]] = relationship(
        order_by="CollectionsTable.created_at"
    )
    assistants: Mapped[list["Assistants"]] = relationship(
        order_by="Assistants.created_at"
    )
    services: Mapped[list["Services"]] = relationship(order_by="Services.created_at")
    websites: Mapped[list["Websites"]] = relationship(order_by="Websites.created_at")
    integration_knowledge_list: Mapped[list["IntegrationKnowledge"]] = relationship(
        order_by="IntegrationKnowledge.created_at"
    )
    apps: Mapped[list["Apps"]] = relationship(order_by="Apps.created_at")

    completion_models_mapping: Mapped[list["SpacesCompletionModels"]] = relationship(
        viewonly=True
    )
    embedding_models_mapping: Mapped[list["SpacesEmbeddingModels"]] = relationship(
        viewonly=True
    )
    transcription_models_mapping: Mapped[list["SpacesTranscriptionModels"]] = (
        relationship(viewonly=True)
    )


class SpacesEmbeddingModels(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), primary_key=True
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(EmbeddingModels.id, ondelete="CASCADE"), primary_key=True
    )


class SpacesCompletionModels(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), primary_key=True
    )
    completion_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="CASCADE"), primary_key=True
    )


class SpacesTranscriptionModels(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), primary_key=True
    )
    transcription_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(TranscriptionModels.id, ondelete="CASCADE"), primary_key=True
    )


class SpacesUsers(BaseCrossReference):
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column()

    # Relationships
    user: Mapped["Users"] = relationship()
