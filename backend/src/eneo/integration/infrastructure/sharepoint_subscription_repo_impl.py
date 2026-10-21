from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from typing_extensions import override

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SharePointSubscriptionDBModel,
)
from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.domain.repositories.sharepoint_subscription_repo import (
    SharePointSubscriptionExists,
    SharePointSubscriptionRepository,
)
from eneo.integration.infrastructure.mappers.sharepoint_subscription_mapper import (
    SharePointSubscriptionMapper,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_USER_SITE_UNIQUE_CONSTRAINT = "uq_sharepoint_subscription_user_site"
_OWN_TRANSACTION_LOCK_TIMEOUT = "120s"


def _violates_user_site_uniqueness(exc: IntegrityError) -> bool:
    """True when the driver error names the (user integration, site) constraint.

    asyncpg carries the name on ``constraint_name``; other drivers only have it
    in the message. Anything else (FK, NOT NULL) is a genuine failure.
    """
    orig: object = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        if candidate is None:
            continue
        if getattr(candidate, "constraint_name", None) == _USER_SITE_UNIQUE_CONSTRAINT:
            return True
        if _USER_SITE_UNIQUE_CONSTRAINT in str(candidate):
            return True
    return False


class SharePointSubscriptionRepositoryImpl(
    BaseRepoImpl[
        SharePointSubscription,
        SharePointSubscriptionDBModel,
        SharePointSubscriptionMapper,
    ],
    SharePointSubscriptionRepository,
):
    """SQLAlchemy implementation of SharePointSubscriptionRepository."""

    def __init__(self, session: "AsyncSession", mapper: SharePointSubscriptionMapper):
        super().__init__(
            session=session, model=SharePointSubscriptionDBModel, mapper=mapper
        )

    @override
    async def add(self, obj: SharePointSubscription) -> SharePointSubscription:
        # The insert runs in a SAVEPOINT so a unique violation leaves the
        # caller's transaction usable for the re-read.
        try:
            async with self.session.begin_nested():
                return await super().add(obj)
        except IntegrityError as exc:
            if not _violates_user_site_uniqueness(exc):
                raise
            raise SharePointSubscriptionExists(
                obj.user_integration_id, obj.site_id
            ) from exc

    @override
    async def get_by_user_and_site(
        self, user_integration_id: UUID, site_id: str
    ) -> Optional[SharePointSubscription]:
        """Get subscription for a specific user+site combination."""
        stmt = sa.select(SharePointSubscriptionDBModel).where(
            sa.and_(
                SharePointSubscriptionDBModel.user_integration_id
                == user_integration_id,
                SharePointSubscriptionDBModel.site_id == site_id,
            )
        )
        result = await self.session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            return None

        return self.mapper.to_entity(db_obj)

    @override
    async def lock_user_site(
        self, user_integration_id: UUID, site_id: str
    ) -> Optional[SharePointSubscription]:
        # A row lock cannot cover a subscription that does not exist yet, so
        # the pair is locked by name; the unique constraint stays the backstop.
        await self.session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    sa.func.hashtextextended(
                        f"sharepoint_subscription:{user_integration_id}:{site_id}", 0
                    )
                )
            )
        )
        # The identity map may hold the row as this transaction first read it.
        stmt = (
            sa.select(SharePointSubscriptionDBModel)
            .where(
                SharePointSubscriptionDBModel.user_integration_id
                == user_integration_id,
                SharePointSubscriptionDBModel.site_id == site_id,
            )
            .execution_options(populate_existing=True)
        )
        db_obj = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if db_obj is None else self.mapper.to_entity(db_obj)

    @override
    async def get_by_subscription_id(
        self, subscription_id: str
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

    @override
    async def list_expiring_before(
        self, expires_before: datetime
    ) -> List[SharePointSubscription]:
        """List all subscriptions expiring before the given datetime."""
        stmt = (
            sa.select(SharePointSubscriptionDBModel)
            .where(SharePointSubscriptionDBModel.expires_at <= expires_before)
            .order_by(SharePointSubscriptionDBModel.expires_at.asc())
        )

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()

        return self.mapper.to_entities(db_objs)

    @override
    async def list_all(self) -> List[SharePointSubscription]:
        """List all active subscriptions."""
        stmt = sa.select(SharePointSubscriptionDBModel).order_by(
            SharePointSubscriptionDBModel.created_at.desc()
        )

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()

        return self.mapper.to_entities(db_objs)

    @override
    async def list_by_tenant(
        self,
        tenant_id: UUID,
    ) -> List[SharePointSubscription]:
        """List all subscriptions for a tenant."""
        stmt = (
            sa.select(SharePointSubscriptionDBModel)
            .join(
                UserIntegrationDBModel,
                SharePointSubscriptionDBModel.user_integration_id
                == UserIntegrationDBModel.id,
            )
            .where(UserIntegrationDBModel.tenant_id == tenant_id)
            .order_by(SharePointSubscriptionDBModel.created_at.desc())
        )

        result = await self.session.execute(stmt)
        db_objs = result.scalars().all()
        return self.mapper.to_entities(db_objs)

    @override
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
                SharePointSubscriptionDBModel.user_integration_id
                == UserIntegrationDBModel.id,
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

    @override
    async def count_references(self, subscription_id: UUID) -> int:
        """Count how many integration_knowledge records reference this subscription."""
        stmt = (
            sa.select(sa.func.count())
            .select_from(IntegrationKnowledgeDBModel)
            .where(
                IntegrationKnowledgeDBModel.sharepoint_subscription_id
                == subscription_id
            )
        )

        result = await self.session.execute(stmt)
        count = result.scalar_one()

        return count

    @override
    async def link_unreferenced_knowledge(
        self, subscription: SharePointSubscription
    ) -> int:
        unreferenced = (
            sa.select(IntegrationKnowledgeDBModel.id)
            .where(
                IntegrationKnowledgeDBModel.sharepoint_subscription_id.is_(None),
                IntegrationKnowledgeDBModel.user_integration_id
                == subscription.user_integration_id,
                sa.func.coalesce(
                    IntegrationKnowledgeDBModel.site_id,
                    IntegrationKnowledgeDBModel.drive_id,
                )
                == subscription.site_id,
            )
            .with_for_update(skip_locked=True)
        )
        stmt = (
            sa.update(IntegrationKnowledgeDBModel)
            .where(IntegrationKnowledgeDBModel.id.in_(unreferenced))
            .where(IntegrationKnowledgeDBModel.sharepoint_subscription_id.is_(None))
            .values(sharepoint_subscription_id=subscription.id)
        )
        result = await self.session.execute(stmt)
        return affected_row_count(result)

    @override
    @asynccontextmanager
    async def own_transaction(
        self,
    ) -> AsyncGenerator["SharePointSubscriptionRepositoryImpl"]:
        from eneo.database.database import sessionmanager

        async with sessionmanager.session() as session, session.begin():
            # Waiting longer than any Graph round trip means a lock the
            # caller's own transaction holds; fail instead of hanging.
            await session.execute(
                sa.text(f"SET LOCAL lock_timeout = '{_OWN_TRANSACTION_LOCK_TIMEOUT}'")
            )
            yield SharePointSubscriptionRepositoryImpl(
                session=session, mapper=self.mapper
            )
