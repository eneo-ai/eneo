from datetime import datetime
from typing import TYPE_CHECKING, Sequence, cast
from uuid import UUID

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
        # Check if sharepoint_subscription was eager loaded via selectinload
        # We need to use sqlalchemy.inspect to check if the attribute was loaded
        # without triggering a lazy load (which causes greenlet errors in async context)
        from sqlalchemy import inspect

        sharepoint_subscription = None
        try:
            insp = inspect(record)
            if insp is not None and "sharepoint_subscription" not in insp.unloaded:
                sharepoint_subscription = record.sharepoint_subscription
        except Exception:
            # If inspection fails, fall back to None
            pass

        user_integration = UserIntegrationFactory.create_entity(record.user_integration)
        sharepoint_subscription = None
        if record.sharepoint_subscription is not None:
            subscription = record.sharepoint_subscription
            sharepoint_subscription = SharePointSubscription(
                id=cast(UUID, subscription.id),
                user_integration_id=cast(UUID, subscription.user_integration_id),
                site_id=cast(str, subscription.site_id),
                subscription_id=cast(str, subscription.subscription_id),
                drive_id=cast(str, subscription.drive_id),
                expires_at=cast(datetime, subscription.expires_at),
                created_at=cast(datetime | None, subscription.created_at),
                updated_at=cast(datetime | None, subscription.updated_at),
            )

        return IntegrationKnowledge(
            id=cast(UUID, record.id),
            name=cast(str, record.name),
            original_name=cast(str | None, getattr(record, "original_name", None)),
            url=cast(str | None, record.url),
            tenant_id=cast(UUID, record.tenant_id),
            space_id=cast(UUID, record.space_id),
            user_integration=user_integration,
            embedding_model=embedding_model,
            created_at=cast(datetime | None, record.created_at),
            updated_at=cast(datetime | None, record.updated_at),
            size=cast(int | None, record.size),
            site_id=cast(str | None, record.site_id),
            last_synced_at=cast(datetime | None, record.last_synced_at),
            last_sync_summary=cast(dict[str, int] | None, record.last_sync_summary),
            sharepoint_subscription_id=cast(
                UUID | None, getattr(record, "sharepoint_subscription_id", None)
            ),
            sharepoint_subscription=sharepoint_subscription,
            delta_token=cast(str | None, getattr(record, "delta_token", None)),
            folder_id=cast(str | None, getattr(record, "folder_id", None)),
            folder_path=cast(str | None, getattr(record, "folder_path", None)),
            selected_item_type=cast(
                str | None, getattr(record, "selected_item_type", None)
            ),
            resource_type=cast(str | None, getattr(record, "resource_type", None)),
            drive_id=cast(str | None, getattr(record, "drive_id", None)),
            wrapper_id=cast(UUID | None, getattr(record, "wrapper_id", None)),
            wrapper_name=cast(str | None, getattr(record, "wrapper_name", None)),
        )

    @classmethod
    def create_entities(
        cls,
        records: Sequence["IntegrationKnowledgeDBModel"],
        embedding_models: Sequence["EmbeddingModel"],
    ) -> list["IntegrationKnowledge"]:
        entities = []
        for record in records:
            embedding_model = next(
                (
                    embedding_model
                    for embedding_model in embedding_models
                    if embedding_model.id == record.embedding_model_id
                ),
                None,
            )
            if embedding_model:
                entities.append(
                    cls.create_entity(record=record, embedding_model=embedding_model)
                )
            else:
                raise ValueError(f"Embedding model not found for record {record.id}")
        return entities
