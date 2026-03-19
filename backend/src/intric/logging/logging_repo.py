# MIT License

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.logging_table import logging_table
from intric.logging.logging import LoggingDetails, LoggingDetailsInDB


class LoggingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, logging_details: LoggingDetails):
        query = (
            sa.insert(logging_table)
            .values(**logging_details.model_dump())
            .returning(logging_table)
        )

        result = await self.session.execute(query)
        entry_in_db = result.scalar_one()

        return LoggingDetailsInDB.model_validate(entry_in_db)

    async def get(self, id: int):
        query = sa.select(logging_table).where(logging_table.id == id)  # type: ignore[attr-defined]

        result = await self.session.execute(query)
        entry_in_db = result.scalar_one_or_none()

        return LoggingDetailsInDB.model_validate(entry_in_db)
