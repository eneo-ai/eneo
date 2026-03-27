from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class Widgets(BasePublic):
    name: Mapped[str] = mapped_column()
    title: Mapped[str] = mapped_column()
    bot_introduction: Mapped[str] = mapped_column()
    color: Mapped[str] = mapped_column()
    size: Mapped[str] = mapped_column()

    # Foreign keys
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))

    # Relationships
    assistant: Mapped[Assistants] = relationship(viewonly=True)
    tenant: Mapped[Tenants] = relationship(viewonly=True, secondary="users")
