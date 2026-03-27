from sqlalchemy import UUID, Column, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB

from eneo.database.tables.base_class import BasePublic


class Settings(BasePublic):
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"))
    chatbot_widget = Column(JSONB)
