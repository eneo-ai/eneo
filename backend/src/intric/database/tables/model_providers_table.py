from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants


class ModelProviders(BasePublic):
    """Table for storing tenant-specific AI model providers with credentials."""

    __tablename__ = "model_providers"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(nullable=False)
    provider_type: Mapped[str] = mapped_column(nullable=False)  # "openai", "azure", "anthropic"
    credentials: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # Encrypted API keys
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # Additional config like endpoints
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_model_providers_tenant_name"),)
