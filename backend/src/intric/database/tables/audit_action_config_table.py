"""SQLAlchemy model for audit_action_config table.

Stores per-action audit logging configuration for each tenant.
"""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants


class AuditActionConfig(BasePublic):
    """Per-action audit logging configuration.

    Allows granular control over which specific actions are logged
    for each tenant. Complements the category-level configuration.
    """

    __tablename__ = "audit_action_config"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        primary_key=True,
        comment="Action type (e.g., 'user_created', 'file_uploaded')"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="TRUE",
        comment="Whether this action is logged for this tenant"
    )

    # Relationships
    tenant: Mapped[Tenants] = relationship("Tenants")
