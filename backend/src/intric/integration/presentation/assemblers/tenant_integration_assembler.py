from typing import TYPE_CHECKING

from intric.integration.presentation.models import TenantIntegration as TenantIntegrationModel
from intric.integration.presentation.models import TenantIntegrationList

if TYPE_CHECKING:
    from intric.integration.domain.entities.tenant_integration import TenantIntegration


class TenantIntegrationAssembler:
    @classmethod
    def from_domain_to_model(
        cls, item: "TenantIntegration"
    ) -> "TenantIntegrationModel":
        # Only return the TenantIntegration id if it's actually linked to the tenant
        # (i.e., has been enabled via POST /tenant/{integration_id}/)
        # For available-but-not-enabled integrations, id will be None
        return TenantIntegrationModel(
            id=item.id,  # None for not-yet-enabled integrations
            name=item.integration.name,
            description=item.integration.description,
            integration_type=item.integration.integration_type,
            integration_id=item.integration.id,
        )

    @classmethod
    def to_paginated_response(
        cls,
        integrations: list["TenantIntegration"],
    ) -> TenantIntegrationList:
        items = [cls.from_domain_to_model(integration) for integration in integrations]
        return TenantIntegrationList(items=items)
