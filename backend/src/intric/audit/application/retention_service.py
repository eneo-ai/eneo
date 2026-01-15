"""Retention policy service for audit logs."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy


class RetentionPolicyModel(BaseModel):
    """Retention policy model for audit log retention configuration."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    retention_days: int
    last_purge_at: Optional[datetime] = None
    purge_count: int = 0
    created_at: datetime
    updated_at: datetime

    # Conversation retention fields
    conversation_retention_enabled: bool = False
    conversation_retention_days: Optional[int] = None


class RetentionService:
    """Service for managing audit log retention policies."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_policy(self, tenant_id: UUID) -> RetentionPolicyModel:
        """
        Get retention policy for a tenant.

        If no policy exists, creates a default policy with 365 days retention.

        Args:
            tenant_id: Tenant ID

        Returns:
            Retention policy model
        """
        query = select(AuditRetentionPolicy).where(
            AuditRetentionPolicy.tenant_id == tenant_id
        )
        result = await self.session.execute(query)
        policy = result.scalar_one_or_none()

        if policy is None:
            # Create default policy
            policy = await self._create_default_policy(tenant_id)

        return RetentionPolicyModel.model_validate(policy)

    async def _create_default_policy(self, tenant_id: UUID) -> AuditRetentionPolicy:
        """Create default retention policy for a tenant."""
        from sqlalchemy import insert

        query = (
            insert(AuditRetentionPolicy)
            .values(tenant_id=tenant_id, retention_days=365)
            .returning(AuditRetentionPolicy)
        )

        result = await self.session.execute(query)
        return result.scalar_one()

    async def update_policy(
        self,
        tenant_id: UUID,
        retention_days: int,
        conversation_retention_enabled: Optional[bool] = None,
        conversation_retention_days: Optional[int] = None,
    ) -> RetentionPolicyModel:
        """
        Update retention policy for a tenant.

        Args:
            tenant_id: Tenant ID
            retention_days: Number of days to retain audit logs (1-2555)
            conversation_retention_enabled: Enable tenant-wide conversation retention
            conversation_retention_days: Days to retain conversations when enabled

        Returns:
            Updated retention policy

        Raises:
            ValueError: If retention_days is out of valid range
        """
        # Validate retention period
        if retention_days < 1:
            raise ValueError("Minimum retention period is 1 day")
        if retention_days > 2555:  # ~7 years
            raise ValueError("Maximum retention period is 2555 days (7 years)")

        # Validate conversation retention
        if conversation_retention_days is not None:
            if conversation_retention_days < 1:
                raise ValueError("Minimum conversation retention period is 1 day")
            if conversation_retention_days > 2555:
                raise ValueError("Maximum conversation retention period is 2555 days")

        # Build update values
        update_values = {
            "retention_days": retention_days,
            "updated_at": datetime.now(timezone.utc),
        }

        if conversation_retention_enabled is not None:
            update_values["conversation_retention_enabled"] = conversation_retention_enabled

        if conversation_retention_days is not None:
            update_values["conversation_retention_days"] = conversation_retention_days

        # Update policy
        query = (
            update(AuditRetentionPolicy)
            .where(AuditRetentionPolicy.tenant_id == tenant_id)
            .values(**update_values)
            .returning(AuditRetentionPolicy)
        )

        result = await self.session.execute(query)
        policy = result.scalar_one_or_none()

        if policy is None:
            # Create policy if it doesn't exist
            from sqlalchemy import insert

            create_values = {
                "tenant_id": tenant_id,
                "retention_days": retention_days,
            }
            if conversation_retention_enabled is not None:
                create_values["conversation_retention_enabled"] = conversation_retention_enabled
            if conversation_retention_days is not None:
                create_values["conversation_retention_days"] = conversation_retention_days

            query = (
                insert(AuditRetentionPolicy)
                .values(**create_values)
                .returning(AuditRetentionPolicy)
            )
            result = await self.session.execute(query)
            policy = result.scalar_one()

        return RetentionPolicyModel.model_validate(policy)

    async def purge_old_logs(self, tenant_id: UUID) -> int:
        """
        Purge (soft delete) audit logs older than the retention period.

        Args:
            tenant_id: Tenant ID

        Returns:
            Number of logs purged
        """
        from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

        # Get retention policy
        policy = await self.get_policy(tenant_id)

        # Purge old logs (HARD delete - permanent removal for compliance)
        repository = AuditLogRepositoryImpl(self.session)
        purged_count = await repository.hard_delete_old_logs(
            tenant_id=tenant_id,
            retention_days=policy.retention_days,
        )

        # Update purge tracking
        if purged_count > 0:
            query = (
                update(AuditRetentionPolicy)
                .where(AuditRetentionPolicy.tenant_id == tenant_id)
                .values(
                    last_purge_at=datetime.now(timezone.utc),
                    purge_count=AuditRetentionPolicy.purge_count + 1,
                )
            )
            await self.session.execute(query)

        return purged_count
