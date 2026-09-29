from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository


@pytest.mark.asyncio
async def test_public_key_origin_query_filters_relaxed_tenants_in_sql():
    session = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[
                ["https://b.example", "https://a.example"],
                ["https://a.example", 123],
                None,
            ]
        )
    )
    repo = ApiKeysV2Repository(cast(AsyncSession, session))

    patterns = await repo.list_relaxed_tenant_public_key_origin_patterns()

    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    selected_columns = sql.partition("FROM")[0]

    assert "tenants.api_key_policy" not in selected_columns
    assert "require_tenant_allowed_origin" in sql
    assert "IS false" in sql
    assert patterns == ["https://a.example", "https://b.example"]
