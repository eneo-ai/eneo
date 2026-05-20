from typing import Any, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.questions_table import Questions


class McpToolReference(BasePublic):
    __tablename__ = "mcp_tool_references"  # type: ignore[assignment]

    tool_call_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    mcp_tool_name: Mapped[Optional[str]] = mapped_column(nullable=True)
    uri: Mapped[str] = mapped_column()
    mime_type: Mapped[Optional[str]] = mapped_column(nullable=True)
    content: Mapped[Optional[str]] = mapped_column(nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Foreign keys
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey(Questions.id, ondelete="CASCADE"), index=True
    )
