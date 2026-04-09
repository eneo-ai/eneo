"""Database table for audit retention policies."""

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from intric.database.tables.base_class import BaseWithTableName, TimestampMixin


class AuditRetentionPolicy(TimestampMixin, BaseWithTableName):
    """Table for per-tenant audit log retention configuration."""

    __tablename__ = "audit_retention_policies"  # type: ignore[assignment]

    # Tenant ID is primary key (one policy per tenant)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    # Audit Log Retention Configuration
    retention_days = Column(Integer, nullable=False, default=365)

    # Conversation History Retention Configuration
    conversation_retention_enabled = Column(Boolean, nullable=False, default=False)
    conversation_retention_days = Column(Integer, nullable=True)

    # Purge Tracking
    last_purge_at = Column(TIMESTAMP(timezone=True), nullable=True)
    purge_count = Column(Integer, nullable=False, default=0)
