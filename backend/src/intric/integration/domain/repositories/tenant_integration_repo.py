from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from intric.integration.domain.entities.tenant_integration import TenantIntegration


class TenantIntegrationRepository(ABC):
    @abstractmethod
    async def query(self, **filters) -> list["TenantIntegration"]: ...

    @abstractmethod
    async def one_or_none(
        self, id: "UUID | None" = None, **filters
    ) -> "TenantIntegration | None": ...

    @abstractmethod
    async def one(self, id: "UUID | None" = None, **filters) -> "TenantIntegration": ...

    @abstractmethod
    async def add(self, obj: "TenantIntegration") -> "TenantIntegration": ...

    @abstractmethod
    async def delete(self, id: "UUID") -> None: ...

    @abstractmethod
    async def delete_by_tenant(self, id: "UUID", tenant_id: "UUID") -> None: ...
