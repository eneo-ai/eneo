from typing import TYPE_CHECKING

from eneo.integration.domain.entities.tenant_integration import TenantIntegration

if TYPE_CHECKING:
    from eneo.database.tables.integration_table import (
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
        return [
            TenantIntegrationFactory.create_entity(record) for record in records
        ]
