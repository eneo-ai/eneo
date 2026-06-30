from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users


class Services(BasePublic):
    name: Mapped[str] = mapped_column()
    prompt: Mapped[str] = mapped_column()
    output_format: Mapped[Optional[str]] = mapped_column()
    json_schema: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    completion_model_kwargs: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL"),
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
    )

    # relationships
    groups: Mapped[list[CollectionsTable]] = relationship(
        secondary="services_groups", order_by=CollectionsTable.created_at
    )
    user: Mapped[Users] = relationship()
    completion_model: Mapped[CompletionModels] = relationship()
    service_groups: Mapped[list["ServicesGroups"]] = relationship(viewonly=True)


class ServicesGroups(BaseCrossReference):
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey(Services.id, ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="CASCADE"), primary_key=True
    )
