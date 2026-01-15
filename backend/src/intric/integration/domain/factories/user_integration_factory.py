from typing import TYPE_CHECKING

from intric.integration.domain.entities.user_integration import UserIntegration

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        UserIntegration as UserIntegrationDBModel,
    )


class UserIntegrationFactory:
    @staticmethod
    def create_entity(record: "UserIntegrationDBModel") -> UserIntegration:
        return UserIntegration(
            tenant_integration=record.tenant_integration,
            user_id=record.user_id,  # Can be None for tenant_app integrations
            id=record.id,
            authenticated=record.authenticated,
            auth_type=record.auth_type,
            tenant_app_id=record.tenant_app_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def create_entities(
        records: list["UserIntegrationDBModel"],
    ) -> list[UserIntegration]:
        return [
            UserIntegrationFactory.create_entity(record) for record in records
        ]
