"""Persist an explicitly replaced relationship without rewriting unchanged rows.

Callers own authorization, validation and locking the parent before replacement.
The baseline is the stored relationship, never a filtered resource projection.
Omitted relationships must not call these functions; an empty selection clears
the relationship, including targets that are currently unavailable for reading.
"""

from collections.abc import Collection, Mapping
from typing import TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from eneo.database.tables.base_class import BaseWithTableName

Key = TypeVar("Key", UUID, str)
Value = TypeVar("Value", str, bool, str | None)


async def replace_association_ids(
    session: AsyncSession,
    table: type[BaseWithTableName],
    owner: InstrumentedAttribute[UUID],
    owner_id: UUID,
    target: InstrumentedAttribute[Key],
    desired: Collection[Key],
) -> None:
    current = set(await session.scalars(sa.select(target).where(owner == owner_id)))
    selected = set(desired)
    removed = current - selected
    added = selected - current
    if removed:
        await session.execute(
            sa.delete(table).where(owner == owner_id, target.in_(removed))
        )
    if added:
        await session.execute(
            sa.insert(table).values(
                [{owner.key: owner_id, target.key: key} for key in added]
            )
        )


async def replace_association_values(
    session: AsyncSession,
    table: type[BaseWithTableName],
    owner: InstrumentedAttribute[UUID],
    owner_id: UUID,
    target: InstrumentedAttribute[UUID],
    value: InstrumentedAttribute[Value],
    desired: Mapping[UUID, Value],
) -> None:
    rows = await session.execute(sa.select(target, value).where(owner == owner_id))
    current = {key: setting for key, setting in rows}
    removed = current.keys() - desired.keys()
    if removed:
        await session.execute(
            sa.delete(table).where(owner == owner_id, target.in_(removed))
        )
    added = desired.keys() - current.keys()
    if added:
        await session.execute(
            sa.insert(table).values(
                [
                    {owner.key: owner_id, target.key: key, value.key: desired[key]}
                    for key in added
                ]
            )
        )
    for key in current.keys() & desired.keys():
        if current[key] != desired[key]:
            await session.execute(
                sa.update(table)
                .where(owner == owner_id, target == key)
                .values({value.key: desired[key]})
            )
