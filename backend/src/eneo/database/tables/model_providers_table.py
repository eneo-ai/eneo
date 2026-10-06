from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, Date, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants


class ModelProviders(BasePublic):
    """Table for storing tenant-specific AI model providers with credentials."""

    __tablename__ = "model_providers"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(nullable=False)
    provider_type: Mapped[str] = mapped_column(
        nullable=False
    )  # "openai", "azure", "anthropic"
    credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )  # Encrypted API keys
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # Additional config like endpoints
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    # Admin-entered: few provider APIs report when a key expires.
    key_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Latest connection check against the stored credentials; NULL until one
    # runs and again after the credentials or endpoint change.
    connection_status: Mapped[str | None] = mapped_column(nullable=True)
    connection_error: Mapped[str | None] = mapped_column(nullable=True)
    connection_checked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_model_providers_tenant_name"),
        CheckConstraint(
            "(connection_status IS NULL AND connection_checked_at IS NULL"
            " AND connection_error IS NULL)"
            " OR (connection_status = 'ok' AND connection_checked_at IS NOT NULL"
            " AND connection_error IS NULL)"
            " OR (connection_status = 'failed' AND connection_checked_at IS NOT NULL"
            " AND connection_error IS NOT NULL)",
            name="ck_model_providers_connection_check",
        ),
    )
