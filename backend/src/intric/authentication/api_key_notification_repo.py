from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from intric.authentication.auth_models import (
    ApiKeyNotificationPreferencesResponse,
    ApiKeyNotificationSubscription,
    ApiKeyNotificationSubscriptionSource,
    ApiKeyNotificationTargetType,
)
from intric.database.database import AsyncSession
from intric.database.tables.api_key_notification_tables import (
    ApiKeyNotificationPreference,
    ApiKeyNotificationSubscriptionTable,
)


class ApiKeyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_preferences(
        self,
        user_id: UUID,
    ) -> ApiKeyNotificationPreferencesResponse | None:
        stmt = (
            sa.select(ApiKeyNotificationPreference)
            .where(ApiKeyNotificationPreference.user_id == user_id)
            .limit(1)
        )
        record = await self.session.scalar(stmt)
        if record is None:
            return None

        return ApiKeyNotificationPreferencesResponse(
            enabled=record.enabled,
            days_before_expiry=record.days_before_expiry,
            auto_follow_published_assistants=record.auto_follow_published_assistants,
            auto_follow_published_apps=record.auto_follow_published_apps,
        )

    async def upsert_preferences(
        self,
        *,
        user_id: UUID,
        preferences: ApiKeyNotificationPreferencesResponse,
    ) -> ApiKeyNotificationPreferencesResponse:
        stmt = (
            insert(ApiKeyNotificationPreference)
            .values(
                user_id=user_id,
                enabled=preferences.enabled,
                days_before_expiry=preferences.days_before_expiry,
                auto_follow_published_assistants=preferences.auto_follow_published_assistants,
                auto_follow_published_apps=preferences.auto_follow_published_apps,
            )
            .on_conflict_do_update(
                index_elements=[ApiKeyNotificationPreference.user_id],
                set_={
                    "enabled": preferences.enabled,
                    "days_before_expiry": preferences.days_before_expiry,
                    "auto_follow_published_assistants": preferences.auto_follow_published_assistants,
                    "auto_follow_published_apps": preferences.auto_follow_published_apps,
                },
            )
        )
        await self.session.execute(stmt)
        return preferences

    async def list_subscriptions(
        self,
        user_id: UUID,
    ) -> list[ApiKeyNotificationSubscription]:
        stmt = (
            sa.select(ApiKeyNotificationSubscriptionTable)
            .where(ApiKeyNotificationSubscriptionTable.user_id == user_id)
            .order_by(
                ApiKeyNotificationSubscriptionTable.target_type.asc(),
                ApiKeyNotificationSubscriptionTable.target_id.asc(),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [
            ApiKeyNotificationSubscription(
                target_type=ApiKeyNotificationTargetType(row.target_type),
                target_id=row.target_id,
            )
            for row in rows
        ]

    async def add_subscription(
        self,
        *,
        user_id: UUID,
        subscription: ApiKeyNotificationSubscription,
        source: ApiKeyNotificationSubscriptionSource = (
            ApiKeyNotificationSubscriptionSource.MANUAL
        ),
    ) -> bool:
        stmt = (
            insert(ApiKeyNotificationSubscriptionTable)
            .values(
                user_id=user_id,
                target_type=subscription.target_type.value,
                target_id=subscription.target_id,
                source=source.value,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ApiKeyNotificationSubscriptionTable.user_id,
                    ApiKeyNotificationSubscriptionTable.target_type,
                    ApiKeyNotificationSubscriptionTable.target_id,
                ]
            )
            .returning(ApiKeyNotificationSubscriptionTable.id)
        )
        inserted_id = await self.session.scalar(stmt)
        return inserted_id is not None

    async def delete_subscription(
        self,
        *,
        user_id: UUID,
        target_type: str,
        target_id: UUID,
    ) -> None:
        stmt = sa.delete(ApiKeyNotificationSubscriptionTable).where(
            ApiKeyNotificationSubscriptionTable.user_id == user_id,
            ApiKeyNotificationSubscriptionTable.target_type == target_type,
            ApiKeyNotificationSubscriptionTable.target_id == target_id,
        )
        await self.session.execute(stmt)
