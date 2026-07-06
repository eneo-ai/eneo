from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.base.base_entity import Entity

if TYPE_CHECKING:
    from eneo.integration.domain.entities.integration import Integration


class TenantIntegration(Entity):
    def __init__(
        self,
        tenant_id: UUID,
        integration: "Integration",
        id: Optional[UUID] = None,
    ):
        super().__init__(id=id)
        self.tenant_id = tenant_id
        self.integration = integration

    @property
    def integration_type(self) -> str:
        return self.integration.integration_type
