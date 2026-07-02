from typing import Any, Dict, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.integration_table import Integration as IntegrationDBModel
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.factories.integration_factory import IntegrationFactory


class IntegrationMapper(EntityMapper[Integration, IntegrationDBModel]):
    @override
    def to_db_dict(self, entity: Integration) -> Dict[str, Any]:
        return {
            "name": entity.name,
            "description": entity.description,
            "integration_type": entity.integration_type,
        }

    @override
    def to_entity(self, db_model: IntegrationDBModel) -> Integration:
        return IntegrationFactory.create_entity(record=db_model)

    @override
    def to_entities(self, db_models: Sequence[IntegrationDBModel]) -> list[Integration]:
        return IntegrationFactory.create_entities(records=db_models)
