from typing import Optional
from uuid import UUID

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic


class Settings(BasePublic):
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    chatbot_widget = Column(JSONB)
