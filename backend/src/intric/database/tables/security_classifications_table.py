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
        CompletionModelSettings,
        EmbeddingModelSettings,
        TranscriptionModelSettings,
    )
    from intric.database.tables.image_models_table import ImageModelSettings
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
    completion_model_settings: Mapped[list["CompletionModelSettings"]] = relationship(
        back_populates="security_classification",
        order_by="CompletionModelSettings.created_at",
    )
    embedding_model_settings: Mapped[list["EmbeddingModelSettings"]] = relationship(
        back_populates="security_classification",
        order_by="EmbeddingModelSettings.created_at",
    )
    transcription_model_settings: Mapped[list["TranscriptionModelSettings"]] = (
        relationship(
            back_populates="security_classification",
            order_by="TranscriptionModelSettings.created_at",
        )
    )
    image_model_settings: Mapped[list["ImageModelSettings"]] = relationship(
        back_populates="security_classification",
        order_by="ImageModelSettings.created_at",
    )
    spaces: Mapped[list["Spaces"]] = relationship(
        back_populates="security_classification", order_by="Spaces.created_at"
    )
