"""Junction models must match the migrated schema.

``BaseCrossReference`` models carry both timestamps. ``GroupsSpaces`` and
``WebsitesSpaces`` only track creation: distribution links are inserted or
deleted, so these models use ``CreatedAtMixin`` instead. Include them explicitly
to keep the original schema-drift regressions covered regardless of base class.
Selecting each model's full column set against the migrated test database catches
missing tables or columns even when the tables contain no rows.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import eneo.database.tables  # noqa: F401  (registers every table module)
from eneo.database.tables.base_class import Base, BaseCrossReference, BaseWithTableName
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.websites_spaces_table import WebsitesSpaces

CROSS_REFERENCE_MODELS = sorted(
    {
        mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, BaseCrossReference)
    }
    | {GroupsSpaces, WebsitesSpaces},
    key=lambda model: model.__tablename__,
)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    CROSS_REFERENCE_MODELS,
    ids=[model.__tablename__ for model in CROSS_REFERENCE_MODELS],
)
async def test_cross_reference_model_columns_exist_in_migrated_schema(
    async_session: AsyncSession, model: type[BaseWithTableName]
) -> None:
    # LIMIT 1 keeps the query cheap; Postgres still validates every selected
    # column, so a missing one raises UndefinedColumn even on an empty table.
    await async_session.execute(sa.select(model.__table__).limit(1))
