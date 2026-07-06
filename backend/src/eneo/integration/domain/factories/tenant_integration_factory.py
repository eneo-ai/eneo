from typing import TYPE_CHECKING, Sequence

from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.factories.integration_factory import IntegrationFactory

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
            integration=IntegrationFactory.create_entity(record.integration),
        )

    @staticmethod
    def create_entities(
        records: Sequence["TenantIntegrationDBModel"],
    ) -> list[TenantIntegration]:
        return [TenantIntegrationFactory.create_entity(record) for record in records]
