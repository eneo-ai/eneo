from uuid import UUID

import sqlalchemy as sa

from eneo.connector_protocol.installation import ConnectorInstallation
from eneo.database.database import AsyncSession
from eneo.database.tables.connector_installations_table import ConnectorInstallations


class ConnectorInstallationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, *, tenant_id: UUID, name: str, base_url: str, key_digest: str
    ) -> ConnectorInstallation:
        row = await self.session.scalar(
            sa.insert(ConnectorInstallations)
            .values(
                tenant_id=tenant_id, name=name, base_url=base_url, key_digest=key_digest
            )
            .returning(ConnectorInstallations)
        )
        return ConnectorInstallation.model_validate(row)

    async def get_by_tenant(self, tenant_id: UUID) -> list[ConnectorInstallation]:
        rows = await self.session.scalars(
            sa.select(ConnectorInstallations)
            .where(ConnectorInstallations.tenant_id == tenant_id)
            .order_by(ConnectorInstallations.created_at, ConnectorInstallations.id)
        )
        return [ConnectorInstallation.model_validate(row) for row in rows]

    async def get_for_tenant(
        self, installation_id: UUID, tenant_id: UUID
    ) -> ConnectorInstallation | None:
        row = await self.session.scalar(
            sa.select(ConnectorInstallations).where(
                ConnectorInstallations.id == installation_id,
                ConnectorInstallations.tenant_id == tenant_id,
            )
        )
        return None if row is None else ConnectorInstallation.model_validate(row)

    async def get_by_key_digest(self, key_digest: str) -> ConnectorInstallation | None:
        """The installation a call's shared key belongs to, in any tenant: the
        key is what says which tenant the call is for."""
        row = await self.session.scalar(
            sa.select(ConnectorInstallations).where(
                ConnectorInstallations.key_digest == key_digest
            )
        )
        return None if row is None else ConnectorInstallation.model_validate(row)

    async def any_exists(self) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(sa.exists().where(ConnectorInstallations.id.is_not(None)))
            )
        )

    async def delete(self, installation_id: UUID, tenant_id: UUID) -> None:
        await self.session.execute(
            sa.delete(ConnectorInstallations).where(
                ConnectorInstallations.id == installation_id,
                ConnectorInstallations.tenant_id == tenant_id,
            )
        )
