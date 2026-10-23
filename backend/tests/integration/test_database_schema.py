"""Every registered table's declared columns must exist after Alembic migrations.

Use the same metadata as Alembic, including tables without an ORM class. The
shared integration fixtures build a disposable PostgreSQL database with
``alembic upgrade head``, not ``metadata.create_all()``. Each table has its own
test ID so a failure identifies the model/migration mismatch to investigate.

This checks table and column existence only, not types, constraints, defaults,
indexes or upgrades of existing customer data. See the database schema check
section in the architecture guide for the scope and troubleshooting steps.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import eneo.database.tables  # noqa: F401  (registers tables, as in alembic/env.py)
from eneo.database.tables.base_class import Base

TABLES = sorted(Base.metadata.tables.values(), key=lambda table: table.fullname)
assert TABLES, "No database tables registered; check eneo.database.tables imports"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("table", TABLES, ids=[table.fullname for table in TABLES])
async def test_registered_table_columns_exist_in_migrated_schema(
    async_session: AsyncSession, table: sa.Table
) -> None:
    # PostgreSQL resolves every selected column even with LIMIT 0. No rows are
    # read or changed, and empty tables get the same coverage as populated ones.
    await async_session.execute(sa.select(table).limit(0))
