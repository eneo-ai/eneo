from typing import TYPE_CHECKING

from intric.integration.presentation.models import Integration as IntegrationModel
from intric.integration.presentation.models import IntegrationList, IntegrationType

if TYPE_CHECKING:
    from intric.integration.domain.entities.integration import Integration


class IntegrationAssembler:
    @classmethod
    def from_domain_to_model(cls, item: "Integration") -> "IntegrationModel":
        return IntegrationModel(
            id=item.id,
            name=item.name,
            description=item.description,
            integration_type=IntegrationType(item.integration_type),
        )

    @classmethod
    def to_paginated_response(
        cls,
        integrations: list["Integration"],
    ) -> IntegrationList:
        items = [cls.from_domain_to_model(integration) for integration in integrations]
        return IntegrationList(items=items)
