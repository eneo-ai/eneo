from datetime import datetime
from typing import Any, Dict, List, Sequence, cast
from uuid import UUID

from intric.base.base_entity import EntityMapper
from intric.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SharePointSubscriptionDBModel,
)
from intric.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)


class SharePointSubscriptionMapper(
    EntityMapper[SharePointSubscription, SharePointSubscriptionDBModel]
):
    def to_db_dict(self, entity: SharePointSubscription) -> Dict[str, Any]:
        result = {
            "id": entity.id,
            "user_integration_id": entity.user_integration_id,
            "site_id": entity.site_id,
            "subscription_id": entity.subscription_id,
            "drive_id": entity.drive_id,
            "expires_at": entity.expires_at,
        }
        # Only include timestamps if they're set (not None)
        # This allows database defaults to apply for new entities
        if entity.created_at is not None:
            result["created_at"] = entity.created_at
        if entity.updated_at is not None:
            result["updated_at"] = entity.updated_at
        return result

    def to_entity(
        self, db_model: SharePointSubscriptionDBModel
    ) -> SharePointSubscription:
        return SharePointSubscription(
            id=cast(UUID, db_model.id),
            user_integration_id=cast(UUID, db_model.user_integration_id),
            site_id=cast(str, db_model.site_id),
            subscription_id=cast(str, db_model.subscription_id),
            drive_id=cast(str, db_model.drive_id),
            expires_at=cast(datetime, db_model.expires_at),
            created_at=cast(datetime | None, db_model.created_at),
            updated_at=cast(datetime | None, db_model.updated_at),
        )

    def to_entities(
        self, db_models: Sequence[SharePointSubscriptionDBModel]
    ) -> List[SharePointSubscription]:
        return [self.to_entity(db_model) for db_model in db_models]
