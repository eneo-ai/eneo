from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SharePointSubscriptionDBModel
)
from intric.database.tables.integration_table import IntegrationKnowledge as IntegrationKnowledgeDBModel
from intric.database.tables.integration_table import UserIntegration as UserIntegrationDBModel
from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription
from intric.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionRepository
)
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.integration.infrastructure.mappers.sharepoint_subscription_mapper import (
    SharePointSubscriptionMapper
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SharePointSubscriptionRepositoryImpl(
    BaseRepoImpl[SharePointSubscription, SharePointSubscriptionDBModel, SharePointSubscriptionMapper],
    SharePointSubscriptionRepository
):
    """SQLAlchemy implementation of SharePointSubscriptionRepository."""

    def __init__(self, session: "AsyncSession", mapper: SharePointSubscriptionMapper):
        super().__init__(session=session, model=SharePointSubscriptionDBModel, mapper=mapper)

    async def get_by_user_and_site(
        self,
        user_integration_id: UUID,
        site_id: str
    ) -> Optional[SharePointSubscription]:
        """Get subscription for a specific user+site combination."""
        stmt = sa.select(SharePointSubscriptionDBModel).where(
            sa.and_(
                SharePointSubscriptionDBModel.user_integration_id == user_integration_id,
                SharePointSubscriptionDBModel.site_id == site_id
            )
        )
        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            return None

        return self.mapper.to_entity(db_obj)

    async def get_by_subscription_id(
        self,
        subscription_id: str
    ) -> Optional[SharePointSubscription]:
        """Get subscription by Microsoft Graph subscription ID."""
        stmt = sa.select(SharePointSubscriptionDBModel).where(
            SharePointSubscriptionDBModel.subscription_id == subscription_id
        )
        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            return None

        return self.mapper.to_entity(db_obj)

    async def list_expiring_before(
        self,
        expires_before: datetime
    ) -> List[SharePointSubscription]:
        """List all subscriptions expiring before the given datetime."""
        stmt = sa.select(SharePointSubscriptionDBModel).where(
            SharePointSubscriptionDBModel.expires_at <= expires_before
        ).order_by(SharePointSubscriptionDBModel.expires_at.asc())

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()

        return self.mapper.to_entities(db_objs)

    async def list_all(self) -> List[SharePointSubscription]:
        """List all active subscriptions."""
        stmt = sa.select(SharePointSubscriptionDBModel).order_by(
            SharePointSubscriptionDBModel.created_at.desc()
        )

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()

        return self.mapper.to_entities(db_objs)

    async def list_by_tenant(
        self,
        tenant_id: UUID,
    ) -> List[SharePointSubscription]:
        """List all subscriptions for a tenant."""
        stmt = (
            sa.select(SharePointSubscriptionDBModel)
            .join(
                UserIntegrationDBModel,
                SharePointSubscriptionDBModel.user_integration_id == UserIntegrationDBModel.id,
            )
            .where(UserIntegrationDBModel.tenant_id == tenant_id)
            .order_by(SharePointSubscriptionDBModel.created_at.desc())
        )

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()
        return self.mapper.to_entities(db_objs)

    async def one_by_tenant(
        self,
        subscription_id: UUID,
        tenant_id: UUID,
    ) -> Optional[SharePointSubscription]:
        """Get a subscription by ID scoped to tenant."""
        stmt = (
            sa.select(SharePointSubscriptionDBModel)
            .join(
                UserIntegrationDBModel,
                SharePointSubscriptionDBModel.user_integration_id == UserIntegrationDBModel.id,
            )
            .where(
                sa.and_(
                    SharePointSubscriptionDBModel.id == subscription_id,
                    UserIntegrationDBModel.tenant_id == tenant_id,
                )
            )
        )

        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()
        if db_obj is None:
            return None
        return self.mapper.to_entity(db_obj)

    async def count_references(
        self,
        subscription_id: UUID
    ) -> int:
        """Count how many integration_knowledge records reference this subscription."""
        stmt = sa.select(sa.func.count()).select_from(
            IntegrationKnowledgeDBModel
        ).where(
            IntegrationKnowledgeDBModel.sharepoint_subscription_id == subscription_id
        )

        result = await self.session.execute(stmt)
        count = result.scalar_one()

        return count
