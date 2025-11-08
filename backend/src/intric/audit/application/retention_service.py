"""Retention policy service for audit logs."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy


class RetentionPolicyModel(BaseModel):
    """Retention policy model."""

    tenant_id: UUID
    retention_days: int
    last_purge_at: Optional[datetime] = None
    purge_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
        self, tenant_id: UUID, retention_days: int
    ) -> RetentionPolicyModel:
        """
        Update retention policy for a tenant.

        Args:
            tenant_id: Tenant ID
            retention_days: Number of days to retain audit logs (90-2555)

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

        # Update policy
        query = (
            update(AuditRetentionPolicy)
            .where(AuditRetentionPolicy.tenant_id == tenant_id)
            .values(retention_days=retention_days, updated_at=datetime.utcnow())
            .returning(AuditRetentionPolicy)
        )

        result = await self.session.execute(query)
        policy = result.scalar_one_or_none()

        if policy is None:
            # Create policy if it doesn't exist
            from sqlalchemy import insert

            query = (
                insert(AuditRetentionPolicy)
                .values(tenant_id=tenant_id, retention_days=retention_days)
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

        # Purge old logs
        repository = AuditLogRepositoryImpl(self.session)
        purged_count = await repository.soft_delete_old_logs(
            tenant_id=tenant_id,
            retention_days=policy.retention_days,
        )

        # Update purge tracking
        if purged_count > 0:
            query = (
                update(AuditRetentionPolicy)
                .where(AuditRetentionPolicy.tenant_id == tenant_id)
                .values(
                    last_purge_at=datetime.utcnow(),
                    purge_count=AuditRetentionPolicy.purge_count + 1,
                )
            )
            await self.session.execute(query)

        return purged_count

    async def purge_all_tenants(self) -> dict:
        """
        Purge old logs for all tenants.

        Returns:
            Dictionary with purge statistics per tenant
        """
        # Get all retention policies
        query = select(AuditRetentionPolicy)
        result = await self.session.execute(query)
        policies = result.scalars().all()

        purge_stats = {}
        for policy in policies:
            purged_count = await self.purge_old_logs(policy.tenant_id)
            purge_stats[str(policy.tenant_id)] = {
                "retention_days": policy.retention_days,
                "purged_count": purged_count,
            }

        return purge_stats
