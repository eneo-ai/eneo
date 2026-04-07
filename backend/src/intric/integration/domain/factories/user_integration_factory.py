from datetime import datetime
from typing import TYPE_CHECKING, Sequence, cast
from uuid import UUID

from intric.integration.domain.entities.user_integration import UserIntegration
from intric.integration.domain.factories.tenant_integration_factory import (
    TenantIntegrationFactory,
)

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        UserIntegration as UserIntegrationDBModel,
    )


class UserIntegrationFactory:
    @staticmethod
    def create_entity(record: "UserIntegrationDBModel") -> UserIntegration:
        return UserIntegration(
            tenant_integration=TenantIntegrationFactory.create_entity(
                record.tenant_integration
            ),
            user_id=record.user_id,  # Can be None for tenant_app integrations
            id=cast(UUID, record.id),
            authenticated=cast(bool, record.authenticated),
            auth_type=cast(str, record.auth_type),
            tenant_app_id=cast(UUID | None, record.tenant_app_id),
            created_at=cast(datetime | None, record.created_at),
            updated_at=cast(datetime | None, record.updated_at),
        )

    @staticmethod
    def create_entities(
        records: Sequence["UserIntegrationDBModel"],
    ) -> list[UserIntegration]:
        return [UserIntegrationFactory.create_entity(record) for record in records]
