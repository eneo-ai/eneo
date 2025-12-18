# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ARRAY, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationsTable,
)
from intric.database.tables.tenant_table import Tenants

if TYPE_CHECKING:
    from intric.database.tables.users_table import Users


class ImageModels(BasePublic):
    """Table for storing image generation model definitions."""

    # Sync key - must match ai_models.yml
    name: Mapped[str] = mapped_column(unique=True)
    # Display name
    nickname: Mapped[str] = mapped_column()

    # Provider info
    family: Mapped[str] = mapped_column()  # openai, azure, flux, etc.
    stability: Mapped[str] = mapped_column()  # stable, experimental
    hosting: Mapped[str] = mapped_column()  # usa, eu, swe
    org: Mapped[Optional[str]] = mapped_column()  # OpenAI, Microsoft, etc.
    description: Mapped[Optional[str]] = mapped_column()

    # Model metadata
    open_source: Mapped[Optional[bool]] = mapped_column()
    is_deprecated: Mapped[bool] = mapped_column(server_default="False")
    hf_link: Mapped[Optional[str]] = mapped_column()

    # Image-specific capabilities
    max_resolution: Mapped[Optional[str]] = mapped_column()  # e.g., '1024x1024'
    supported_sizes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    supported_qualities: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    max_images_per_request: Mapped[int] = mapped_column(server_default="4")

    # Provider configuration
    litellm_model_name: Mapped[Optional[str]] = mapped_column()
    base_url: Mapped[Optional[str]] = mapped_column()


class ImageModelSettings(BaseCrossReference):
    """Per-tenant settings for image generation models."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), primary_key=True
    )
    image_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(ImageModels.id, ondelete="CASCADE"), primary_key=True
    )
    is_org_enabled: Mapped[bool] = mapped_column(server_default="False")
    is_org_default: Mapped[bool] = mapped_column(server_default="False")

    # Security classification relationship
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassificationsTable.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional["SecurityClassificationsTable"]] = (
        relationship(back_populates="image_model_settings")
    )


class GeneratedImages(BasePublic):
    """Table for storing generated images (for history/analytics)."""

    # Relationships
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    image_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ImageModels.id, ondelete="SET NULL"), nullable=True
    )

    # Generation parameters
    prompt: Mapped[str] = mapped_column()
    revised_prompt: Mapped[Optional[str]] = mapped_column()  # If provider revises prompt
    size: Mapped[Optional[str]] = mapped_column()
    quality: Mapped[Optional[str]] = mapped_column()

    # Image data
    blob: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    mimetype: Mapped[str] = mapped_column(nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)

    # Additional metadata (generation params, usage, etc.)
    metadata: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships for eager loading
    image_model: Mapped[Optional["ImageModels"]] = relationship()
    user: Mapped[Optional["Users"]] = relationship()

    __table_args__ = (
        Index("idx_generated_images_tenant", "tenant_id"),
        Index("idx_generated_images_created", "created_at"),
    )
