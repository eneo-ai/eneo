from typing import Any, Dict, Sequence

from typing_extensions import override

from eneo.base.base_entity import EntityMapper
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.factories.user_integration_factory import (
    UserIntegrationFactory,
)


class UserIntegrationMapper(EntityMapper[UserIntegration, UserIntegrationDBModel]):
    @override
    def to_db_dict(self, entity: UserIntegration) -> Dict[str, Any]:
        return {
            "user_id": entity.user_id,
            "tenant_id": entity.tenant_integration.tenant_id,
            "tenant_integration_id": entity.tenant_integration.id,
            "authenticated": entity.authenticated,
            "auth_type": entity.auth_type,
            "tenant_app_id": entity.tenant_app_id,
        }

    @override
    def to_entity(self, db_model: UserIntegrationDBModel) -> UserIntegration:
        return UserIntegrationFactory.create_entity(record=db_model)

    @override
    def to_entities(
        self, db_models: Sequence[UserIntegrationDBModel]
    ) -> list[UserIntegration]:
        return UserIntegrationFactory.create_entities(records=db_models)
