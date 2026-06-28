from typing import Any, Dict, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.factories.sync_log_factory import SyncLogFactory


class SyncLogMapper(EntityMapper[SyncLog, SyncLogDBModel]):
    @override
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

    @override
    def to_entity(self, db_model: SyncLogDBModel) -> SyncLog:
        return SyncLogFactory.create_from_db(record=db_model)

    @override
    def to_entities(self, db_models: Sequence[SyncLogDBModel]) -> list[SyncLog]:
        return [self.to_entity(db_model) for db_model in db_models]
