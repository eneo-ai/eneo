from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BaseCrossReference, BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class Prompts(BasePublic):
    text: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()

    # Foreign keys
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))

    # Relationships
    user: Mapped[Users] = relationship()
    tenant: Mapped[Tenants] = relationship()


class PromptsAssistants(BaseCrossReference):
    prompt_id: Mapped[UUID] = mapped_column(
        ForeignKey(Prompts.id, ondelete="CASCADE"), primary_key=True
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    is_selected: Mapped[bool] = mapped_column()
