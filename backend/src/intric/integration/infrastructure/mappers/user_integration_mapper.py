from typing import Dict, Any, List

from intric.base.base_entity import EntityMapper
from intric.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from intric.integration.domain.entities.user_integration import UserIntegration
from intric.integration.domain.factories.user_integration_factory import (
    UserIntegrationFactory,
)


class UserIntegrationMapper(EntityMapper[UserIntegration, UserIntegrationDBModel]):
    def to_db_dict(self, entity: UserIntegration) -> Dict[str, Any]:
        return {
            "user_id": entity.user_id,
            "tenant_id": entity.tenant_integration.tenant_id,
            "tenant_integration_id": entity.tenant_integration.id,
            "authenticated": entity.authenticated,
            "auth_type": entity.auth_type,
            "tenant_app_id": entity.tenant_app_id,
        }

    def to_entity(self, db_model: UserIntegrationDBModel) -> UserIntegration:
        return UserIntegrationFactory.create_entity(record=db_model)

    def to_entities(
        self, db_models: List[UserIntegrationDBModel]
    ) -> List[UserIntegration]:
        return UserIntegrationFactory.create_entities(records=db_models)
