from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.tenant_table import Tenants


class ScimTokenRepository:
    """Data access for the SCIM bearer-token hash stored on `tenants`.
    The underlying column lives on the `Tenants` table because SCIM tokens are
    a tenant-scoped credential, not a separate entity.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tenant_exists(self, tenant_id: UUID) -> bool:
        result = await self._session.execute(
            sa.select(Tenants.id).where(Tenants.id == tenant_id)
        )
        return result.scalar_one_or_none() is not None

    async def get_token_hash(self, tenant_id: UUID) -> tuple[bool, str | None]:
        """Return `(tenant_exists, token_hash_or_None)`.

        The combined return shape lets callers distinguish "tenant not found"
        from "tenant exists but no token issued" with a single query.
        """
        result = await self._session.execute(
            sa.select(Tenants.scim_token_hash).where(Tenants.id == tenant_id)
        )
        row = result.one_or_none()
        if row is None:
            return (False, None)
        return (True, row[0])

    async def set_token_hash(self, tenant_id: UUID, token_hash: str | None) -> None:
        await self._session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                scim_token_hash=token_hash,
                updated_at=datetime.now(timezone.utc),
            )
        )
