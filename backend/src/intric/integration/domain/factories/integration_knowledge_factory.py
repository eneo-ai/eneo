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
        return IntegrationKnowledge(
            id=record.id,
            name=record.name,
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
            sharepoint_subscription_expires_at=getattr(
                record, "sharepoint_subscription_expires_at", None
            ),
            delta_token=getattr(record, "delta_token", None),
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
