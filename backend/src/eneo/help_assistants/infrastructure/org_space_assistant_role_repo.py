"""Async SQLAlchemy repository for ``org_space_assistant_roles``.

Persistence-only. Service-level invariants (assistant must live in the same
org-space, audit trail writes, etc.) live in the role-assignment service.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.org_space_assistant_roles_table import (
    OrgSpaceAssistantRoles,
)
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.role_assignment import RoleAssignment


class OrgSpaceAssistantRoleRepo:
    def __init__(self, session: AsyncSession, factory: HelperAssistantsFactory) -> None:
        self.session = session
        self.factory = factory

    def _to_domain(self, row: OrgSpaceAssistantRoles | None) -> RoleAssignment | None:
        if row is None:
            return None

        return self.factory.create_role_assignment(
            id=row.id,
            org_space_id=row.org_space_id,
            kind=HelperKind(row.kind),
            assistant_id=row.assistant_id,
            is_enabled=row.is_enabled,
            is_visible_to_users=row.is_visible_to_users,
            created_by_user_id=row.created_by_user_id,
            updated_by_user_id=row.updated_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, assignment: RoleAssignment) -> RoleAssignment:
        stmt = (
            sa.insert(OrgSpaceAssistantRoles)
            .values(
                org_space_id=assignment.org_space_id,
                kind=assignment.kind.value,
                assistant_id=assignment.assistant_id,
                is_enabled=assignment.is_enabled,
                is_visible_to_users=assignment.is_visible_to_users,
                created_by_user_id=assignment.created_by_user_id,
                updated_by_user_id=assignment.updated_by_user_id,
            )
            .returning(OrgSpaceAssistantRoles)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        result = self._to_domain(row)
        assert result is not None
        return result

    async def get_by_id(self, id: UUID) -> RoleAssignment | None:
        stmt = sa.select(OrgSpaceAssistantRoles).where(OrgSpaceAssistantRoles.id == id)
        return self._to_domain(await self.session.scalar(stmt))

    async def get_by_org_space_and_kind(
        self, org_space_id: UUID, kind: HelperKind
    ) -> RoleAssignment | None:
        stmt = sa.select(OrgSpaceAssistantRoles).where(
            OrgSpaceAssistantRoles.org_space_id == org_space_id,
            OrgSpaceAssistantRoles.kind == kind.value,
        )
        return self._to_domain(await self.session.scalar(stmt))

    async def list_for_org_space(self, org_space_id: UUID) -> list[RoleAssignment]:
        stmt = (
            sa.select(OrgSpaceAssistantRoles)
            .where(OrgSpaceAssistantRoles.org_space_id == org_space_id)
            .order_by(OrgSpaceAssistantRoles.created_at)
        )
        result = await self.session.scalars(stmt)
        return [
            assignment
            for row in result
            if (assignment := self._to_domain(row)) is not None
        ]

    async def update(self, assignment: RoleAssignment) -> RoleAssignment:
        stmt = (
            sa.update(OrgSpaceAssistantRoles)
            .values(
                assistant_id=assignment.assistant_id,
                is_enabled=assignment.is_enabled,
                is_visible_to_users=assignment.is_visible_to_users,
                updated_by_user_id=assignment.updated_by_user_id,
            )
            .where(OrgSpaceAssistantRoles.id == assignment.id)
            .returning(OrgSpaceAssistantRoles)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        result = self._to_domain(row)
        assert result is not None
        return result

    async def delete(self, id: UUID) -> None:
        stmt = sa.delete(OrgSpaceAssistantRoles).where(OrgSpaceAssistantRoles.id == id)
        await self.session.execute(stmt)

    async def exists_active_for_assistant(self, assistant_id: UUID) -> bool:
        stmt = sa.select(
            sa.exists().where(OrgSpaceAssistantRoles.assistant_id == assistant_id)
        )
        result = await self.session.scalar(stmt)
        return bool(result)
