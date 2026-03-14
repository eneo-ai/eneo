"""SQLAlchemy implementation of audit config repository."""

import logging
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.domain.repositories.audit_config_repository import (
    AuditConfigRepository,
)
from intric.database.tables.audit_category_config_table import AuditCategoryConfig

logger = logging.getLogger(__name__)


class AuditConfigRepositoryImpl(AuditConfigRepository):
    """SQLAlchemy implementation of audit category configuration repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_tenant(self, tenant_id: UUID) -> list[tuple[str, bool]]:
        """
        Get all category configurations for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of tuples (category, enabled) for all 7 categories
        """
        query = (
            sa.select(AuditCategoryConfig.category, AuditCategoryConfig.enabled)
            .where(AuditCategoryConfig.tenant_id == tenant_id)
            .order_by(AuditCategoryConfig.category)
        )

        result = await self.session.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def find_by_tenant_and_category(
        self, tenant_id: UUID, category: str
    ) -> tuple[str, bool, dict] | None:
        """
        Get configuration for a specific category.

        Args:
            tenant_id: Tenant identifier
            category: Category name

        Returns:
            Tuple of (category, enabled, action_overrides) or None if not found
        """
        query = sa.select(
            AuditCategoryConfig.category,
            AuditCategoryConfig.enabled,
            AuditCategoryConfig.action_overrides,
        ).where(
            sa.and_(
                AuditCategoryConfig.tenant_id == tenant_id,
                AuditCategoryConfig.category == category,
            )
        )

        result = await self.session.execute(query)
        row = result.first()

        if row is None:
            return None

        return (row[0], row[1], row[2] or {})

    async def find_all_by_tenant(self, tenant_id: UUID) -> list[tuple[str, bool, dict]]:
        """
        Get all category configurations for a tenant in a single batch query.

        This is more efficient than calling find_by_tenant_and_category multiple times
        when you need all categories at once (e.g., for action config retrieval).

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of tuples (category, enabled, action_overrides) for all existing configs
        """
        query = sa.select(
            AuditCategoryConfig.category,
            AuditCategoryConfig.enabled,
            AuditCategoryConfig.action_overrides,
        ).where(AuditCategoryConfig.tenant_id == tenant_id)

        result = await self.session.execute(query)
        return [(row[0], row[1], row[2] or {}) for row in result.all()]

    async def update(
        self,
        tenant_id: UUID,
        category: str,
        enabled: bool,
        action_overrides: dict | None = None,
    ) -> None:
        """
        Update or insert category configuration (upsert).

        Args:
            tenant_id: Tenant identifier
            category: Category name
            enabled: New enabled state
            action_overrides: Optional dict of action overrides (JSONB)

        Note:
            This method does NOT commit the transaction. The caller is responsible
            for committing the session.
        """
        values = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "category": category,
            "enabled": enabled,
        }
        if action_overrides is not None:
            values["action_overrides"] = action_overrides

        stmt = insert(AuditCategoryConfig).values(**values)

        # PostgreSQL-specific upsert using ON CONFLICT
        update_set = {"enabled": enabled, "updated_at": sa.func.now()}
        if action_overrides is not None:
            update_set["action_overrides"] = action_overrides

        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "category"],
            set_=update_set,
        )

        await self.session.execute(stmt)
        # NOTE: Don't commit here - let the service/caller handle transaction boundaries

        logger.info(
            f"Updated audit category config: tenant={tenant_id}, "
            f"category={category}, enabled={enabled}"
        )
