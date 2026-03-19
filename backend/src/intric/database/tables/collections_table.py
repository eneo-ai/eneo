from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.base_class import BasePublic
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class CollectionsTable(BasePublic):
    __tablename__ = "groups"  # type: ignore[assignment]

    name: Mapped[str] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    embedding_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(EmbeddingModels.id, ondelete="SET NULL"),
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE")
    )

    # relationships
    user: Mapped[Users] = relationship()
    embedding_model: Mapped[Optional[EmbeddingModels]] = relationship()
