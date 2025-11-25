from typing import TYPE_CHECKING

from intric.integration.presentation.models import (
    UserIntegration as UserIntegrationModel,
)
from intric.integration.presentation.models import UserIntegrationList

if TYPE_CHECKING:
    from intric.integration.domain.entities.user_integration import UserIntegration


class UserIntegrationAssembler:
    @classmethod
    def from_domain_to_model(cls, item: "UserIntegration") -> "UserIntegrationModel":
        return UserIntegrationModel(
            id=item.id,
            tenant_integration_id=item.tenant_integration.id,
            connected=item.authenticated,
            name=item.tenant_integration.integration.name,
            integration_type=item.tenant_integration.integration.integration_type,
            description=item.tenant_integration.integration.description,
            auth_type=item.auth_type,
            tenant_app_id=item.tenant_app_id,
        )

    @classmethod
    def to_paginated_response(
        cls,
        integrations: list["UserIntegration"],
    ) -> UserIntegrationList:
        items = [cls.from_domain_to_model(integration) for integration in integrations]
        return UserIntegrationList(items=items)
