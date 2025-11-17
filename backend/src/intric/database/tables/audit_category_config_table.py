"""Database table for audit category configuration."""

from sqlalchemy import Boolean, Column, String, TIMESTAMP, CheckConstraint, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from intric.database.tables.base_class import BasePublic


class AuditCategoryConfig(BasePublic):
    """
    Table for storing per-tenant audit category configuration.

    Allows admins to control which categories of audit events are logged.
    """

    __tablename__ = "audit_category_config"

    # Composite Primary Key
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    category = Column(
        String(50),
        nullable=False,
        primary_key=True,
    )

    # Configuration State
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="TRUE",
    )

    # Timestamps
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="NOW()",
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="NOW()",
        onupdate="NOW()",
    )

    # Constraints and Indexes
    __table_args__ = (
        # Check constraint for valid category names
        CheckConstraint(
            "category IN ('admin_actions', 'user_actions', 'security_events', "
            "'file_operations', 'integration_events', 'system_actions', 'audit_access')",
            name="ck_audit_category_config_category_valid",
        ),
        # Index for fast lookups (tenant_id, category is already covered by PK)
        Index("idx_audit_category_config_lookup", "tenant_id", "category"),
    )
