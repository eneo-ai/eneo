from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic

if TYPE_CHECKING:
    from intric.database.tables.tenant_table import Tenants
    from intric.database.tables.users_table import Users


class TenantSharePointApp(BasePublic):
    """
    Stores Azure AD application credentials for SharePoint access.
    One app registration per tenant for organization-wide SharePoint access
    without person-dependency.
    """

    __tablename__ = "tenant_sharepoint_apps"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False, unique=True
    )
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    certificate_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_domain: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # e.g., "contoso.onmicrosoft.com"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tenant: Mapped["Tenants"] = relationship("Tenants", back_populates="sharepoint_app")
    created_by_user: Mapped["Users"] = relationship("Users", foreign_keys=[created_by])
