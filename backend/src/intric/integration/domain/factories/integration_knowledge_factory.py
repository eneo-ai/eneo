from typing import TYPE_CHECKING, Sequence

from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from intric.integration.domain.factories.user_integration_factory import (
    UserIntegrationFactory,
)

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        IntegrationKnowledge as IntegrationKnowledgeDBModel,
    )


class IntegrationKnowledgeFactory:
    @classmethod
    def create_entity(
        cls, record: "IntegrationKnowledgeDBModel", embedding_model: "EmbeddingModel"
    ) -> IntegrationKnowledge:
        user_integration = UserIntegrationFactory.create_entity(record.user_integration)
        sharepoint_subscription = None
        if record.sharepoint_subscription is not None:
            subscription = record.sharepoint_subscription
            sharepoint_subscription = SharePointSubscription(
                id=subscription.id,
                user_integration_id=subscription.user_integration_id,
                site_id=subscription.site_id,
                subscription_id=subscription.subscription_id,
                drive_id=subscription.drive_id,
                expires_at=subscription.expires_at,
                consecutive_renewal_failures=subscription.consecutive_renewal_failures,
                last_renewal_failed_at=subscription.last_renewal_failed_at,
                last_renewal_error=subscription.last_renewal_error,
                last_webhook_received_at=subscription.last_webhook_received_at,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            )

        return IntegrationKnowledge(
            id=record.id,
            name=record.name or "",
            original_name=getattr(record, "original_name", None),
            url=record.url,
            tenant_id=record.tenant_id,
            space_id=record.space_id,
            user_integration=user_integration,
            embedding_model=embedding_model,
            created_at=record.created_at,
            updated_at=record.updated_at,
            size=record.size,
            site_id=record.site_id,
            last_synced_at=record.last_synced_at,
            last_sync_summary=record.last_sync_summary,
            sharepoint_subscription_id=getattr(
                record, "sharepoint_subscription_id", None
            ),
            sharepoint_subscription=sharepoint_subscription,
            delta_token=getattr(record, "delta_token", None),
            folder_id=getattr(record, "folder_id", None),
            folder_path=getattr(record, "folder_path", None),
            selected_item_type=getattr(record, "selected_item_type", None),
            resource_type=getattr(record, "resource_type", None),
            drive_id=getattr(record, "drive_id", None),
            wrapper_id=getattr(record, "wrapper_id", None),
            wrapper_name=getattr(record, "wrapper_name", None),
        )

    @classmethod
    def create_entities(
        cls,
        records: Sequence["IntegrationKnowledgeDBModel"],
        embedding_models: Sequence["EmbeddingModel"],
    ) -> list["IntegrationKnowledge"]:
        entities: list[IntegrationKnowledge] = []
        for record in records:
            embedding_model = next(
                (em for em in embedding_models if em.id == record.embedding_model_id),
                None,
            )
            if embedding_model:
                entities.append(
                    cls.create_entity(record=record, embedding_model=embedding_model)
                )
            else:
                raise ValueError(f"Embedding model not found for record {record.id}")
        return entities
