from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import ASGITransport, AsyncClient

from intric.database.database import get_session_with_transaction
from intric.scim.app import scim_app
from intric.scim.auth import require_scim_auth
from intric.scim.deps import get_scim_group_service, get_scim_user_service
from intric.scim.services.group_service import ScimGroupService
from intric.scim.services.user_service import ScimUserService
from intric.server.main import app

TEST_BEARER_TOKEN = "test-scim-token"
TEST_TENANT_ID = uuid4()

_bearer = HTTPBearer(auto_error=False)


def _check_test_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UUID:
    """Auth stub: accepts TEST_BEARER_TOKEN without a DB lookup, rejects everything else."""
    if credentials is None or credentials.credentials != TEST_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing SCIM bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TEST_TENANT_ID


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_BEARER_TOKEN}"}


@pytest.fixture
async def client() -> AsyncClient:
    scim_app.dependency_overrides[require_scim_auth] = _check_test_token
    scim_app.dependency_overrides[get_scim_user_service] = lambda: AsyncMock(
        spec=ScimUserService
    )
    scim_app.dependency_overrides[get_scim_group_service] = lambda: AsyncMock(
        spec=ScimGroupService
    )

    def _make_session():
        session = AsyncMock()
        session.begin_nested = MagicMock(return_value=AsyncMock())
        return session

    scim_app.dependency_overrides[get_session_with_transaction] = _make_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    scim_app.dependency_overrides.clear()
