from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.users_table import Users


class ApiKeys(BasePublic):
    key: Mapped[str] = mapped_column(index=True)
    truncated_key: Mapped[str] = mapped_column()
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), unique=True
    )
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("assistants.id", ondelete="CASCADE"), unique=True
    )
