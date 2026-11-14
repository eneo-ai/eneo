import secrets
from uuid import UUID

from eneo.connector_protocol.installation import ConnectorInstallation
from eneo.connector_protocol.installation_repo import ConnectorInstallationRepository
from eneo.connector_protocol.verification import key_digest
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.users.user import UserInDB

# A tenant trusts a handful of installations at most; the bound keeps the list
# an administrator can read and a leaked admin session from filling the table.
MAX_INSTALLATIONS_PER_TENANT = 10


class ConnectorInstallationService:
    """What a tenant administrator does with the installations the tenant trusts."""

    def __init__(self, user: UserInDB, repo: ConnectorInstallationRepository) -> None:
        self.user = user
        self.repo = repo

    @validate_permissions(Permission.ADMIN)
    async def list(self) -> list[ConnectorInstallation]:
        return await self.repo.get_by_tenant(self.user.tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def add(
        self, *, name: str, base_url: str
    ) -> tuple[ConnectorInstallation, str]:
        """Trust an installation. Returns it with its shared key, which exists
        in the clear only in this answer."""
        existing = await self.repo.get_by_tenant(self.user.tenant_id)
        if len(existing) >= MAX_INSTALLATIONS_PER_TENANT:
            raise BadRequestException(
                f"At most {MAX_INSTALLATIONS_PER_TENANT} installations can be added."
            )
        if any(installation.base_url == base_url for installation in existing):
            raise BadRequestException(
                "An installation with this address has already been added."
            )
        key = secrets.token_urlsafe(32)
        installation = await self.repo.add(
            tenant_id=self.user.tenant_id,
            name=name,
            base_url=base_url,
            key_digest=key_digest(key),
        )
        return installation, key

    @validate_permissions(Permission.ADMIN)
    async def remove(self, installation_id: UUID) -> ConnectorInstallation:
        """Stop trusting an installation: its key is refused from now on."""
        installation = await self.repo.get_for_tenant(
            installation_id, self.user.tenant_id
        )
        if installation is None:
            raise NotFoundException("Installation not found.")
        await self.repo.delete(installation.id, self.user.tenant_id)
        return installation
