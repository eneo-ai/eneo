from typing import Any, Dict, List

from intric.base.base_entity import EntityMapper
from intric.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SharePointSubscriptionDBModel,
)
from intric.integration.domain.entities.sharepoint_subscription import SharePointSubscription


class SharePointSubscriptionMapper(EntityMapper[SharePointSubscription, SharePointSubscriptionDBModel]):
    def to_db_dict(self, entity: SharePointSubscription) -> Dict[str, Any]:
        return {
            "id": entity.id,
            "user_integration_id": entity.user_integration_id,
            "site_id": entity.site_id,
            "subscription_id": entity.subscription_id,
            "drive_id": entity.drive_id,
            "expires_at": entity.expires_at,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    def to_entity(self, db_model: SharePointSubscriptionDBModel) -> SharePointSubscription:
        return SharePointSubscription(
            id=db_model.id,
            user_integration_id=db_model.user_integration_id,
            site_id=db_model.site_id,
            subscription_id=db_model.subscription_id,
            drive_id=db_model.drive_id,
            expires_at=db_model.expires_at,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    def to_entities(
        self, db_models: List[SharePointSubscriptionDBModel]
    ) -> List[SharePointSubscription]:
        return [self.to_entity(db_model) for db_model in db_models]
