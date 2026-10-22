"""Names of the principals that started flow runs, read for run listings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.users_table import Users


@dataclass(frozen=True, slots=True)
class FlowRunStarterUser:
    id: UUID
    username: str | None
    email: str


@dataclass(frozen=True, slots=True)
class FlowRunStarterServicePrincipal:
    id: UUID
    display_name: str


class FlowRunStarterRepository:
    """Reads only the naming columns, and only inside one tenant."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_users(
        self, *, tenant_id: UUID, user_ids: Iterable[UUID]
    ) -> dict[UUID, FlowRunStarterUser]:
        ids = tuple(dict.fromkeys(user_ids))
        if not ids:
            return {}
        rows = await self.session.execute(
            sa.select(Users.id, Users.username, Users.email)
            .where(Users.tenant_id == tenant_id)
            .where(Users.id.in_(ids))
        )
        return {
            row.id: FlowRunStarterUser(
                id=row.id, username=row.username, email=row.email
            )
            for row in rows
        }

    async def list_service_principals(
        self, *, tenant_id: UUID, service_principal_ids: Iterable[UUID]
    ) -> dict[UUID, FlowRunStarterServicePrincipal]:
        ids = tuple(dict.fromkeys(service_principal_ids))
        if not ids:
            return {}
        rows = await self.session.execute(
            sa.select(ServicePrincipals.id, ServicePrincipals.display_name)
            .where(ServicePrincipals.tenant_id == tenant_id)
            .where(ServicePrincipals.id.in_(ids))
        )
        return {
            row.id: FlowRunStarterServicePrincipal(
                id=row.id, display_name=row.display_name
            )
            for row in rows
        }
