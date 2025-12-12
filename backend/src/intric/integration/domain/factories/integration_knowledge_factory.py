from typing import TYPE_CHECKING

from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
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
            if "sharepoint_subscription" not in insp.unloaded:
                sharepoint_subscription = record.sharepoint_subscription
        except Exception:
            # If inspection fails, fall back to None
            pass

        return IntegrationKnowledge(
            id=record.id,
            name=record.name,
            original_name=getattr(record, "original_name", None),
            url=record.url,
            tenant_id=record.tenant_id,
            space_id=record.space_id,
            user_integration=record.user_integration,
            embedding_model=embedding_model,
            created_at=record.created_at,
            updated_at=record.updated_at,
            size=record.size,
            site_id=record.site_id,
            last_synced_at=record.last_synced_at,
            last_sync_summary=record.last_sync_summary,
            sharepoint_subscription_id=getattr(record, "sharepoint_subscription_id", None),
            sharepoint_subscription=sharepoint_subscription,
            delta_token=getattr(record, "delta_token", None),
            folder_id=getattr(record, "folder_id", None),
            folder_path=getattr(record, "folder_path", None),
            selected_item_type=getattr(record, "selected_item_type", None),
            resource_type=getattr(record, "resource_type", None),
            drive_id=getattr(record, "drive_id", None),
        )

    @classmethod
    def create_entities(
        cls, records: list["IntegrationKnowledgeDBModel"], embedding_models: list["EmbeddingModel"]
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
                entities.append(cls.create_entity(record=record, embedding_model=embedding_model))
            else:
                raise ValueError(f"Embedding model not found for record {record.id}")
        return entities
