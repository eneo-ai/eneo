# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
)
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.roles.permissions import Permission, validate_permissions
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.tenants.tenant_service import TenantService
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
        SecurityClassificationRepoImpl,
    )


class SecurityClassificationService:
    """Service for managing security levels."""

    def __init__(
        self,
        user: UserInDB,
        repo: "SecurityClassificationRepoImpl",
        tenant_service: TenantService,
    ):
        self.user = user
        self.repo = repo
        self.tenant_service = tenant_service

    @validate_permissions(Permission.ADMIN)
    async def create_security_classification(
        self, name: str, description: Optional[str], set_lowest_security: bool = True
    ) -> SecurityClassification:
        db_classifications = await self.repo.all()

        security_classification = SecurityClassification.create(
            tenant_id=self.user.tenant_id,
            name=name,
            description=description,
        )
        for sc in db_classifications:
            if sc.name == name:
                raise BadRequestException(
                    f"Security classification with name '{name}' already exists"
                )

        added_sc = await self.repo.add(security_classification=security_classification)

        if set_lowest_security:
            new_security_classifications = [added_sc] + db_classifications
        else:
            new_security_classifications = db_classifications + [added_sc]

        for i, sc in enumerate(new_security_classifications):
            sc.security_level = i
            await self.repo.update(sc)

        return added_sc

    async def get_security_classification(self, id: UUID) -> SecurityClassification:
        security_classification = await self.repo.one(id=id)
        return security_classification

    async def list_security_classifications(self) -> list[SecurityClassification]:
        """List all security levels for the current tenant ordered by security_level."""
        return await self.repo.all()

    @validate_permissions(Permission.ADMIN)
    async def update_security_levels(
        self, security_classifications: list[UUID]
    ) -> list[SecurityClassification]:
        db_classifications = await self.repo.all()
        db_classifications_map = {sc.id: sc for sc in db_classifications}

        # Validate all IDs exist before making any updates
        for sc_id in security_classifications:
            if sc_id not in db_classifications_map:
                raise NotFoundException(f"Security classification with ID {sc_id} not found")

        for db_sc_id in list(db_classifications_map.keys()):
            if db_sc_id not in security_classifications:
                raise BadRequestException(
                    f"Security classification with ID {db_sc_id} not found in the provided list"
                )

        # Update all classifications in memory first
        updated_domains = []
        for i, sc_id in enumerate(security_classifications):
            existing_sc = db_classifications_map[sc_id]
            updated_domain = existing_sc.update(security_level=i)
            updated_domains.append(updated_domain)

        # Batch update to database
        result = []
        for updated_domain in updated_domains:
            updated_sc = await self.repo.update(updated_domain)
            result.append(updated_sc)

        return result

    @validate_permissions(Permission.ADMIN)
    async def delete_security_classification(self, id: UUID) -> None:
        await self.repo.delete(id)
        db_security_classifications = await self.repo.all()
        for i, sc in enumerate(db_security_classifications):
            sc.security_level = i
            await self.repo.update(sc)

    @validate_permissions(Permission.ADMIN)
    async def toggle_security_on_tenant(self, enabled: bool):
        return await self.tenant_service.toggle_security(
            tenant_id=self.user.tenant_id,
            enabled=enabled,
        )

    @validate_permissions(Permission.ADMIN)
    async def update_security_classification(
        self,
        id: UUID,
        name: Union[str, NotProvided] = NOT_PROVIDED,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
    ) -> SecurityClassification:
        # Check if any field is provided for update
        if name is NOT_PROVIDED and description is NOT_PROVIDED:
            raise BadRequestException(
                "At least one field (name or description) must be provided for update"
            )
        db_classifications = await self.repo.all()
        for sc in db_classifications:
            if sc.name == name and sc.id != id:
                raise BadRequestException(
                    f"Security classification with name '{name}' already exists"
                )

        # Get the existing security classification
        existing_sc = await self.repo.one(id=id)

        # Update the domain object without changing security_level
        updated_domain_sc = existing_sc.update(name=name, description=description)

        # Save to database and return the updated entity
        return await self.repo.update(updated_domain_sc)
