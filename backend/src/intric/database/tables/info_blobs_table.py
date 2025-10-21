from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.base_class import BasePublic
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites


class InfoBlobs(BasePublic):
    text: Mapped[str] = mapped_column()
    title: Mapped[Optional[str]] = mapped_column()
    url: Mapped[Optional[str]] = mapped_column()
    size: Mapped[int] = mapped_column()
    content_hash: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary(length=32),
        comment="SHA-256 hash of normalized content for change detection",
    )

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    group_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="CASCADE"), index=True
    )
    website_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"), index=True
    )
    embedding_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(EmbeddingModels.id, ondelete="SET NULL"),
    )
    integration_knowledge_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(IntegrationKnowledge.id, ondelete="CASCADE")
    )

    # relationships
    group: Mapped[CollectionsTable] = relationship()
    website: Mapped[Websites] = relationship()
    embedding_model: Mapped[Optional[EmbeddingModels]] = relationship()
    integration_knowledge: Mapped[Optional[IntegrationKnowledge]] = relationship()
