from typing import TYPE_CHECKING

from intric.integration.domain.entities.tenant_integration import TenantIntegration

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        TenantIntegration as TenantIntegrationDBModel,
    )


class TenantIntegrationFactory:
    @staticmethod
    def create_entity(record: "TenantIntegrationDBModel") -> TenantIntegration:
        return TenantIntegration(
            id=record.id,
            tenant_id=record.tenant_id,
            integration=record.integration,
        )

    @staticmethod
    def create_entities(records: list[dict]) -> list[TenantIntegration]:
        return [TenantIntegrationFactory.create_entity(record) for record in records]
