from typing import TYPE_CHECKING
from uuid import UUID

from intric.integration.domain.entities.integration import Integration

if TYPE_CHECKING:
    from intric.integration.domain.repositories.integration_repo import (
        IntegrationRepository,
    )


class IntegrationService:
    def __init__(
        self,
        integration_repo: "IntegrationRepository",
    ) -> None:
        super().__init__()
        self.integration_repo = integration_repo

    async def get_integrations(self) -> list["Integration"]:
        return await self.integration_repo.all()

    async def get_integration_by_id(
        self,
        id: UUID,
    ) -> "Integration":
        return await self.integration_repo.one(id=id)

    async def create_integration(
        self,
        name: str,
        description: str,
        integration_type: str,
    ) -> "Integration":
        return await self.integration_repo.add(
            obj=Integration(
                name=name,
                description=description,
                integration_type=integration_type,
            )
        )
