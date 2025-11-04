from datetime import datetime, timezone
from uuid import UUID
from typing import Optional
import sqlalchemy as sa
from pydantic import EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.roles_table import PredefinedRoles, Roles
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.widget_table import Widgets
from intric.main.exceptions import UniqueException
from intric.main.models import ModelId
from intric.users.user import UserAdd, UserInDB, UserState, UserUpdate

ORG_SPACE_ROLES = {"owner", "ai configurator"}  # Temp, kan bytas senare.

class UsersRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session,
            Users,
            UserInDB,
            with_options=self._get_options(),
        )
        self.session = session

    def _get_options(self):
        return [
            selectinload(Users.roles),
            selectinload(Users.predefined_roles),
            selectinload(Users.tenant).selectinload(Tenants.modules),
            selectinload(Users.api_key),
            selectinload(Users.user_groups),
        ]

    async def _get_model_from_query(self, query, with_deleted: bool = False):
        if not with_deleted:
            query = query.where(Users.deleted_at.is_(None))

        return await self.delegate.get_model_from_query(query)

    async def _get_models_from_query(self, query, with_deleted: bool = False):
        if not with_deleted:
            query = query.where(Users.deleted_at.is_(None))

        return await self.delegate.get_models_from_query(query)

    async def get_user_by_email(
        self, email: EmailStr, with_deleted: bool = False
    ) -> UserInDB:
        # Allow case-insensitive matching
        query = sa.select(Users).where(
            sa.func.lower(Users.email) == sa.func.lower(email)
        )

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_username(
        self, username: str, with_deleted: bool = False
    ) -> UserInDB:
        query = sa.select(Users).where(Users.username == username)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_id(self, id: UUID, with_deleted: bool = False) -> UserInDB:
        query = sa.select(Users).where(Users.id == id)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_assistant_id(
        self, assistant_id: UUID, with_deleted: bool = False
    ) -> UserInDB:
        query = sa.select(Users).join(Assistants).where(Assistants.id == assistant_id)

        return await self._get_model_from_query(query, with_deleted=with_deleted)

    async def get_user_by_id_and_tenant_id(self, id: UUID, tenant_id: UUID) -> UserInDB:
        query = (
            sa.select(Users).where(Users.id == id).where(Users.tenant_id == tenant_id)
        )

        return await self._get_model_from_query(query, with_deleted=False)

    async def get_user_by_widget_id(self, widget_id: UUID) -> UserInDB:
        query = sa.select(Users).join(Widgets).where(Widgets.id == widget_id)
        return await self.delegate.get_model_from_query(query)

    async def get_total_count(
        self, tenant_id: Optional[UUID] = None, filters: Optional[str] = None
    ):
        query = sa.select(sa.func.count(Users.id)).where(Users.deleted_at.is_(None))

        if tenant_id is not None:
            query = query.where(Users.tenant_id == tenant_id)

        if filters is not None:
            query = query.filter(
                sa.func.lower(Users.email).like(f"%{filters.lower()}%")
            )

        return await self.session.scalar(query)

    async def get_all_users(
        self,
        tenant_id: UUID = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        previous: bool = False,
        filters: Optional[str] = None,
    ) -> list[UserInDB]:
        """
        Retrieves a paginated list of users for a specific tenant,
        with optional filtering and cursor-based pagination.
        """
        query = sa.select(Users)

        if tenant_id is not None:
            query = query.where(Users.tenant_id == tenant_id)

        if filters:
            query = query.filter(
                sa.func.lower(Users.email).like(f"%{filters.lower()}%")
            )

        if cursor is not None:
            if previous:
                query = query.where(sa.func.lower(Users.email) <= cursor.lower())
                query = query.order_by(sa.func.lower(Users.email).desc())
                query = query.limit(limit + 1)
                users = await self._get_models_from_query(
                    query=query, with_deleted=False
                )

                return list(reversed(users))
            else:
                query = query.where(sa.func.lower(Users.email) > cursor.lower())

        query = query.order_by(sa.func.lower(Users.email).asc())

        if limit is not None:
            query = query.limit(limit)

        return await self._get_models_from_query(query=query, with_deleted=False)

    async def _get_roles(self, roles: list[ModelId] | None):
        if roles is None:
            return []

        roles_ids = [role.id for role in roles]
        stmt = sa.select(Roles).filter(Roles.id.in_(roles_ids))
        roles = await self.session.scalars(stmt)

        return roles.all()

    async def _get_predefined_roles(self, roles: list[ModelId] | None):
        if roles is None:
            return []

        roles_ids = [role.id for role in roles]
        stmt = sa.select(PredefinedRoles).filter(PredefinedRoles.id.in_(roles_ids))
        roles = await self.session.scalars(stmt)

        return roles.all()

    async def add(self, user: UserAdd):
        try:
            stmt = (
                sa.insert(Users)
                .values(
                    **user.model_dump(
                        exclude_none=True, exclude={"roles", "predefined_roles"}
                    )
                )
                .returning(Users)
            )
            entry_in_db = await self.delegate.get_record_from_query(query=stmt)
            # TODO should be refactored when we will remove int id field from tables
            entry_in_db.roles = await self._get_roles(user.roles)
            entry_in_db.predefined_roles = await self._get_predefined_roles(
                user.predefined_roles
            )

            return UserInDB.model_validate(entry_in_db)
        except IntegrityError as e:
            raise UniqueException("User already exists.") from e

    async def update(self, user: UserUpdate):
        stmt = (
            sa.update(Users)
            .values(
                **user.model_dump(
                    exclude_unset=True, exclude={"id", "roles", "predefined_roles"}
                )
            )
            .where(Users.id == user.id)
            .returning(Users)
        )
        entry_in_db = await self.delegate.get_record_from_query(query=stmt)

        if entry_in_db is None:
            return

        # TODO should be refactored when we will remove int id field from tables
        if "roles" in user.model_dump(exclude_unset=True):
            entry_in_db.roles = await self._get_roles(user.roles)

        if "predefined_roles" in user.model_dump(exclude_unset=True):
            entry_in_db.predefined_roles = await self._get_predefined_roles(
                user.predefined_roles
            )

        return UserInDB.model_validate(entry_in_db)

    async def hard_delete(self, id: int):
        return await self.delegate.delete(id)

    async def soft_delete(self, id: int):
        # Cleanup personal space
        stmt = sa.delete(Spaces).where(Spaces.user_id == id)
        await self.session.execute(stmt)

        stmt = (
            sa.update(Users)
            .values(deleted_at=datetime.now(timezone.utc), state=UserState.DELETED)
            .where(Users.id == id)
            .returning(Users)
        )
        return await self.delegate.get_model_from_query(stmt)

    async def delete(self, id: int, soft_delete: bool = True):
        if soft_delete:
            return await self.soft_delete(id=id)

        return await self.hard_delete(id=id)
    
    async def list_users_by_tenant_id(self, tenant_id: UUID) -> list[UserInDB]:
        query = sa.select(Users).where(
            Users.deleted_at.is_(None),
            Users.tenant_id == tenant_id,
        )
        return await self._get_models_from_query(query, with_deleted=False)
    
    async def list_tenant_admins(self, tenant_id: UUID) -> list["UserInDB"]:
        """
        Returnerar alla users i tenant som har en predefined role som räknas som 'admin'
        """
        q = (
            sa.select(Users)
            .join(Users.predefined_roles)
            .where(
                Users.deleted_at.is_(None),
                Users.tenant_id == tenant_id,
                sa.func.lower(PredefinedRoles.name).in_(ORG_SPACE_ROLES),
            )
        )
        return await self._get_models_from_query(q, with_deleted=False)
