from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.auth_models import ApiKey, ApiKeyInDB
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.api_keys_table import ApiKeys


class ApiKeysRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(session, ApiKeys, ApiKeyInDB)
        self.session = session

    async def get(self, key: str):
        stmt = sa.select(ApiKeys).where(ApiKeys.key == key)
        api_key = await self.session.scalar(stmt)

        if api_key is None:
            return None

        return ApiKeyInDB.model_validate(api_key)

    async def add(
        self,
        api_key: ApiKey,
        user_id: UUID = None,
        assistant_id: int = None,
    ):
        return await self.delegate.add(
            api_key, user_id=user_id, assistant_id=assistant_id
        )

    async def delete_by_user(self, user_id: UUID):
        stmt = sa.delete(ApiKeys).where(ApiKeys.user_id == user_id)
        await self.session.execute(stmt)

    async def delete_by_assistant(self, assistant_id: int):
        stmt = sa.delete(ApiKeys).where(ApiKeys.assistant_id == assistant_id)
        await self.session.execute(stmt)
