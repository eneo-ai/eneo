from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.integration_table import TenantIntegration
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites


class WebsiteIntegrationConfig(BasePublic):
    __tablename__ = "website_integration_configs"  # type: ignore[assignment]

    website_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )

    tenant_integration_id: Mapped[UUID] = mapped_column(
        ForeignKey(TenantIntegration.id, ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    owner_type: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True, index=True
    )
    owner_space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), index=True
    )
    ping_token: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text)
    sitemap_url: Mapped[str] = mapped_column(Text)
    markdown_endpoint_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    markdown_endpoint_method: Mapped[str] = mapped_column(
        Text, server_default="get", nullable=False
    )
    markdown_endpoint_url_location: Mapped[str] = mapped_column(
        Text, server_default="query", nullable=False
    )
    markdown_endpoint_url_param_name: Mapped[str] = mapped_column(
        Text, server_default="url", nullable=False
    )
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    sync_status: Mapped[str] = mapped_column(Text, server_default="idle")
    last_sitemap_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_sync_queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant_integration: Mapped[TenantIntegration] = relationship()
    owner_user: Mapped[Optional[Users]] = relationship(foreign_keys=[owner_user_id])
    owner_space: Mapped[Spaces] = relationship(foreign_keys=[owner_space_id])
    created_by_user: Mapped[Users] = relationship(foreign_keys=[created_by_user_id])
    website: Mapped[Optional[Websites]] = relationship(foreign_keys=[website_id])

    __table_args__ = (
        Index(
            "ix_website_integration_configs_tenant_owner_type",
            "tenant_id",
            "owner_type",
        ),
    )


class WebsiteIntegrationPage(BasePublic):
    __tablename__ = "website_integration_pages"  # type: ignore[assignment]

    website_integration_config_id: Mapped[UUID] = mapped_column(
        ForeignKey(WebsiteIntegrationConfig.id, ondelete="CASCADE"), index=True
    )
    page_url: Mapped[str] = mapped_column(Text)
    website_id: Mapped[UUID] = mapped_column(
        ForeignKey(Websites.id, ondelete="CASCADE"), index=True
    )
    sitemap_lastmod: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_fingerprint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    config: Mapped[WebsiteIntegrationConfig] = relationship()
    website: Mapped[Websites] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "website_integration_config_id",
            "page_url",
            name="uq_website_integration_page_config_url",
        ),
    )
