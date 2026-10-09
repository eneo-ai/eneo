"""Every ``BaseCrossReference`` model must match the migrated schema.

The ORM declares ``created_at`` and ``updated_at`` on every cross-reference
table through ``TimestampMixin``. Only hand-written migrations create the
tables, so a migration that forgets a column leaves a model whose
``sa.select(Model.__table__)``, ORM ``session.add`` with RETURNING, or
``sa.update`` with the ``onupdate`` default fails on Postgres. Selecting the
full column set of each model against the migrated test database turns that
drift into a CI failure instead of a surprise in a later feature test.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import eneo.database.tables  # noqa: F401  (registers every table module)
from eneo.database.tables.base_class import Base, BaseCrossReference

CROSS_REFERENCE_MODELS = sorted(
    (
        mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, BaseCrossReference)
    ),
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
    async_session: AsyncSession, model: type[BaseCrossReference]
) -> None:
    assert CROSS_REFERENCE_MODELS, "no BaseCrossReference models were registered"

    # LIMIT 1 keeps the query cheap; Postgres still validates every selected
    # column, so a missing one raises UndefinedColumn even on an empty table.
    await async_session.execute(sa.select(model.__table__).limit(1))
