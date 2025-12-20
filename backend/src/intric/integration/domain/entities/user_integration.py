from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from intric.base.base_entity import Entity

if TYPE_CHECKING:
    from intric.integration.domain.entities.tenant_integration import TenantIntegration


class UserIntegration(Entity):
    def __init__(
        self,
        tenant_integration: "TenantIntegration",
        user_id: Optional[UUID] = None,
        id: Optional[UUID] = None,
        authenticated: bool = False,
        auth_type: str = "user_oauth",
        tenant_app_id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.user_id = user_id
        self.tenant_integration = tenant_integration
        self.authenticated = authenticated
        self.auth_type = auth_type
        self.tenant_app_id = tenant_app_id

    @property
    def integration_type(self) -> str:
        return self.tenant_integration.integration.integration_type
