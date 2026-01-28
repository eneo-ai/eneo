# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants

if TYPE_CHECKING:
    from intric.database.tables.ai_models_table import (
        CompletionModels,
        EmbeddingModels,
        TranscriptionModels,
    )
    from intric.database.tables.spaces_table import Spaces


class SecurityClassification(BasePublic):
    """Table for storing security levels"""

    __tablename__ = "security_classifications"

    # Core fields
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    security_level: Mapped[int] = mapped_column()

    # Tenant relationship
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
    )
    tenant: Mapped["Tenants"] = relationship()

    # Relationships
    completion_models: Mapped[list["CompletionModels"]] = relationship(
        back_populates="security_classification",
        order_by="CompletionModels.created_at",
    )
    embedding_models: Mapped[list["EmbeddingModels"]] = relationship(
        back_populates="security_classification",
        order_by="EmbeddingModels.created_at",
    )
    transcription_models: Mapped[list["TranscriptionModels"]] = relationship(
        back_populates="security_classification",
        order_by="TranscriptionModels.created_at",
    )
    spaces: Mapped[list["Spaces"]] = relationship(
        back_populates="security_classification", order_by="Spaces.created_at"
    )
