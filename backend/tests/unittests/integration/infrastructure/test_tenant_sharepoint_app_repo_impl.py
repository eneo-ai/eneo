"""The tenant app repository writes inside the caller's transaction."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.integration.infrastructure.tenant_sharepoint_app_repo_impl import (
    TenantSharePointAppRepositoryImpl,
)


async def test_deactivate_does_not_commit_the_callers_transaction():
    """A commit inside a repo method ends the request's session.begin() early,
    so later writes of the same request land outside its transaction."""
    session = AsyncMock()
    session.execute.return_value = MagicMock(rowcount=1)
    repo = TenantSharePointAppRepositoryImpl(session=session, mapper=MagicMock())

    assert await repo.deactivate(uuid4()) is True

    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
