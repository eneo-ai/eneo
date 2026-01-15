"""Database table for audit logs."""

from sqlalchemy import Column, String, Text, ForeignKey, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

from intric.database.tables.base_class import BasePublic


class AuditLog(BasePublic):
    """Table for tracking audit logs with multi-tenant isolation."""

    __tablename__ = "audit_logs"

    # Multi-Tenant Isolation (MANDATORY)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # WHO: Actor Information
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_type = Column(String(50), nullable=False, default="user")

    # WHAT: Action Information
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)

    # WHEN: Temporal Information
    timestamp = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="NOW()",
    )

    # HOW/WHERE: Request Context
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    request_id = Column(UUID(as_uuid=True), nullable=True)

    # WHY/CONTEXT: Business Context
    description = Column(Text, nullable=False)
    log_metadata = Column("metadata", JSONB, nullable=False, default="{}", server_default="{}")

    # Outcome
    outcome = Column(String(20), nullable=False, default="success")
    error_message = Column(Text, nullable=True)

    # Soft Delete (Immutability + Retention)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Indexes for query performance
    __table_args__ = (
        # Primary index for tenant + timestamp queries (most common)
        Index("idx_audit_tenant_timestamp", "tenant_id", "timestamp"),
        # Index for actor queries (GDPR export)
        Index("idx_audit_actor", "tenant_id", "actor_id", "timestamp"),
        # Index for entity queries (resource audit trail)
        Index("idx_audit_entity", "tenant_id", "entity_type", "entity_id"),
        # Index for action queries (compliance review)
        Index("idx_audit_action", "tenant_id", "action", "timestamp"),
        # Partial index for active logs (hot path optimization)
        Index(
            "idx_audit_active",
            "tenant_id",
            "timestamp",
            postgresql_where=(Column("deleted_at").is_(None)),
        ),
    )
