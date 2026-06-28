from typing import Any, Dict, List, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.sharepoint_subscription_table import (
    SharePointSubscription as SharePointSubscriptionDBModel,
)
from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)


class SharePointSubscriptionMapper(
    EntityMapper[SharePointSubscription, SharePointSubscriptionDBModel]
):
    @override
    def to_db_dict(self, entity: SharePointSubscription) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": entity.id,
            "user_integration_id": entity.user_integration_id,
            "site_id": entity.site_id,
            "subscription_id": entity.subscription_id,
            "drive_id": entity.drive_id,
            "expires_at": entity.expires_at,
            "consecutive_renewal_failures": entity.consecutive_renewal_failures,
            "last_renewal_failed_at": entity.last_renewal_failed_at,
            "last_renewal_error": entity.last_renewal_error,
            "last_webhook_received_at": entity.last_webhook_received_at,
        }
        # Only include timestamps if they're set (not None)
        # This allows database defaults to apply for new entities
        if entity.created_at is not None:
            result["created_at"] = entity.created_at
        if entity.updated_at is not None:
            result["updated_at"] = entity.updated_at
        return result

    @override
    def to_entity(
        self, db_model: SharePointSubscriptionDBModel
    ) -> SharePointSubscription:
        return SharePointSubscription(
            id=db_model.id,
            user_integration_id=db_model.user_integration_id,
            site_id=db_model.site_id,
            subscription_id=db_model.subscription_id,
            drive_id=db_model.drive_id,
            expires_at=db_model.expires_at,
            consecutive_renewal_failures=db_model.consecutive_renewal_failures,
            last_renewal_failed_at=db_model.last_renewal_failed_at,
            last_renewal_error=db_model.last_renewal_error,
            last_webhook_received_at=db_model.last_webhook_received_at,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    @override
    def to_entities(
        self, db_models: Sequence[SharePointSubscriptionDBModel]
    ) -> List[SharePointSubscription]:
        return [self.to_entity(db_model) for db_model in db_models]
