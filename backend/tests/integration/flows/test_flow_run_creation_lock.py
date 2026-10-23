"""The tenant's run-creation lock serializes run creations and nothing else.

Every insert that references the tenant checks its foreign key with FOR KEY
SHARE on the tenant row. A creation that held the row FOR UPDATE made all of
them wait for it to commit; FOR NO KEY UPDATE excludes only the next creation.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.database.database import sessionmanager
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _times_out(statement) -> bool:
    try:
        await statement
    except DBAPIError as exc:
        if "lock timeout" in str(exc):
            return True
        raise
    return False


async def test_a_run_creation_lock_excludes_the_next_creation_only(
    setup_database, admin_user
) -> None:
    tenant_id = admin_user.tenant_id
    async with sessionmanager.session() as holder, holder.begin():
        await FlowRunRepository(session=holder).acquire_tenant_run_creation_lock(
            tenant_id=tenant_id
        )

        async with sessionmanager.session() as other, other.begin():
            await other.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
            # A write that references the tenant goes ahead.
            await other.execute(
                sa.text(
                    "INSERT INTO roles (name, permissions, tenant_id) "
                    "VALUES ('run-creation-lock-probe', '{}', :tenant_id)"
                ),
                {"tenant_id": tenant_id},
            )
            await other.rollback()

        async with sessionmanager.session() as other, other.begin():
            await other.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
            # The next run creation waits for this one.
            assert await _times_out(
                FlowRunRepository(session=other).acquire_tenant_run_creation_lock(
                    tenant_id=tenant_id
                )
            )
