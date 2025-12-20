from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.integration_table import IntegrationKnowledge


class SyncLog(BasePublic):
    """Detailed log of each sync operation for an integration."""

    __tablename__ = "sync_logs"

    integration_knowledge_id: Mapped[UUID] = mapped_column(
        ForeignKey(IntegrationKnowledge.id, ondelete="CASCADE"), index=True
    )
    sync_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sync_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    integration_knowledge: Mapped[IntegrationKnowledge] = relationship()
