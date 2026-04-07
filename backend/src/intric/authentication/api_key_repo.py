from typing import Protocol, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.auth_models import ApiKey, ApiKeyInDB
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.api_keys_table import ApiKeys


class _ApiKeyAddDelegate(Protocol):
    async def add(
        self,
        upsert_entry: ApiKey,
        *,
        user_id: UUID | None = None,
        assistant_id: UUID | None = None,
    ) -> ApiKeyInDB: ...


class ApiKeysRepository:
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.delegate: BaseRepositoryDelegate[ApiKeyInDB] = BaseRepositoryDelegate(
            session, ApiKeys, ApiKeyInDB
        )
        self.session = session

    async def get(self, key: str) -> ApiKeyInDB | None:
        stmt = sa.select(ApiKeys).where(ApiKeys.key == key)
        api_key = await self.session.scalar(stmt)

        if api_key is None:
            return None

        return ApiKeyInDB.model_validate(api_key)

    async def add(
        self,
        api_key: ApiKey,
        user_id: UUID | None = None,
        assistant_id: UUID | None = None,
    ) -> ApiKeyInDB:
        add_delegate = cast(_ApiKeyAddDelegate, self.delegate)
        return await add_delegate.add(
            api_key, user_id=user_id, assistant_id=assistant_id
        )

    async def delete_by_user(self, user_id: UUID):
        stmt = sa.delete(ApiKeys).where(ApiKeys.user_id == user_id)
        await self.session.execute(stmt)

    async def delete_by_assistant(self, assistant_id: UUID):
        stmt = sa.delete(ApiKeys).where(ApiKeys.assistant_id == assistant_id)
        await self.session.execute(stmt)
