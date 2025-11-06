from typing import TYPE_CHECKING, Any, Dict, List

from intric.base.base_entity import EntityMapper
from intric.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.domain.factories.integration_knowledge_factory import (
    IntegrationKnowledgeFactory,
)

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel


class IntegrationKnowledgeMapper(EntityMapper[IntegrationKnowledge, IntegrationKnowledgeDBModel]):
    def to_db_dict(self, entity: IntegrationKnowledge) -> Dict[str, Any]:
        return {
            "name": entity.name,
            "tenant_id": entity.tenant_id,
            "url": entity.url,
            "space_id": entity.space_id,
            "user_integration_id": entity.user_integration.id,
            "embedding_model_id": entity.embedding_model.id,
            "size": entity.size,
            "last_synced_at": entity.last_synced_at,
            "last_sync_summary": entity.last_sync_summary,
            "site_id": entity.site_id,
            "sharepoint_subscription_id": entity.sharepoint_subscription_id,
            "sharepoint_subscription_expires_at": entity.sharepoint_subscription_expires_at,
            "delta_token": entity.delta_token,
            "folder_id": entity.folder_id,
            "folder_path": entity.folder_path,
            "selected_item_type": entity.selected_item_type,
        }

    def to_entity(
        self, db_model: IntegrationKnowledgeDBModel, embedding_model: "EmbeddingModel"
    ) -> IntegrationKnowledge:
        return IntegrationKnowledgeFactory.create_entity(
            record=db_model, embedding_model=embedding_model
        )

    def to_entities(
        self, db_models: List[IntegrationKnowledgeDBModel], embedding_models: List["EmbeddingModel"]
    ) -> List[IntegrationKnowledge]:
        return IntegrationKnowledgeFactory.create_entities(
            records=db_models, embedding_models=embedding_models
        )
