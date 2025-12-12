from typing import Any, Dict, List

from intric.base.base_entity import EntityMapper
from intric.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.domain.factories.sync_log_factory import SyncLogFactory


class SyncLogMapper(EntityMapper[SyncLog, SyncLogDBModel]):
    def to_db_dict(self, entity: SyncLog) -> Dict[str, Any]:
        return {
            "integration_knowledge_id": entity.integration_knowledge_id,
            "sync_type": entity.sync_type,
            "status": entity.status,
            "error_message": entity.error_message,
            "sync_metadata": entity.metadata,
            "started_at": entity.started_at,
            "completed_at": entity.completed_at,
        }

    def to_entity(self, db_model: SyncLogDBModel) -> SyncLog:
        return SyncLogFactory.create_from_db(record=db_model)

    def to_entities(self, db_models: List[SyncLogDBModel]) -> List[SyncLog]:
        return [self.to_entity(db_model) for db_model in db_models]
