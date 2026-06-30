from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDBModel,
)
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.factories.integration_knowledge_factory import (
    IntegrationKnowledgeFactory,
)

if TYPE_CHECKING:
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel


class IntegrationKnowledgeMapper(
    EntityMapper[IntegrationKnowledge, IntegrationKnowledgeDBModel]
):
    @override
    def to_db_dict(self, entity: IntegrationKnowledge) -> Dict[str, Any]:
        return {
            "name": entity.name,
            "original_name": entity.original_name,
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
            "delta_token": entity.delta_token,
            "folder_id": entity.folder_id,
            "folder_path": entity.folder_path,
            "selected_item_type": entity.selected_item_type,
            "resource_type": entity.resource_type,
            "drive_id": entity.drive_id,
            "wrapper_id": entity.wrapper_id,
            "wrapper_name": entity.wrapper_name,
        }

    @override
    def to_entity(
        self,
        db_model: IntegrationKnowledgeDBModel,
        *,
        embedding_model: EmbeddingModel | None = None,
    ) -> IntegrationKnowledge:
        if embedding_model is None:
            raise ValueError("embedding_model is required")
        return IntegrationKnowledgeFactory.create_entity(
            record=db_model, embedding_model=embedding_model
        )

    @override
    def to_entities(
        self,
        db_models: Sequence[IntegrationKnowledgeDBModel],
        *,
        embedding_models: Sequence[EmbeddingModel] | None = None,
    ) -> List[IntegrationKnowledge]:
        if embedding_models is None:
            raise ValueError("embedding_models is required")
        return IntegrationKnowledgeFactory.create_entities(
            records=db_models, embedding_models=embedding_models
        )
