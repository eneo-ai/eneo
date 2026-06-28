from typing import Any, Dict, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.factories.tenant_integration_factory import (
    TenantIntegrationFactory,
)


class TenantIntegrationMapper(
    EntityMapper[TenantIntegration, TenantIntegrationDBModel]
):
    @override
    def to_db_dict(self, entity: TenantIntegration) -> Dict[str, Any]:
        return {
            "tenant_id": entity.tenant_id,
            "integration_id": entity.integration.id,
        }

    @override
    def to_entity(self, db_model: TenantIntegrationDBModel) -> TenantIntegration:
        return TenantIntegrationFactory.create_entity(record=db_model)

    @override
    def to_entities(
        self, db_models: Sequence[TenantIntegrationDBModel]
    ) -> list[TenantIntegration]:
        return TenantIntegrationFactory.create_entities(records=db_models)
