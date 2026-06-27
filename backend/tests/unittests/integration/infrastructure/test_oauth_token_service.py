from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.integration.infrastructure.oauth_token_service import OauthTokenService


@pytest.fixture
def token():
    t = MagicMock()
    t.access_token = "old-access"
    t.refresh_token = "old-refresh"
    t.token_type.is_confluence = True
    t.token_type.is_sharepoint = False
    return t


@pytest.fixture
def service(token):
    repo = AsyncMock()
    repo.one.return_value = token
    repo.update.side_effect = lambda obj: obj
    confluence = AsyncMock()
    sharepoint = AsyncMock()
    svc = OauthTokenService(
        oauth_token_repo=repo,
        confluence_auth_service=confluence,
        sharepoint_auth_service=sharepoint,
    )
    return svc, confluence, token


class TestRefreshAndUpdateToken:
    async def test_keeps_existing_refresh_token_when_response_omits_it(self, service):
        svc, confluence, token = service
        confluence.refresh_access_token.return_value = {"access_token": "new-access"}

        result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.access_token == "new-access"
        assert result.refresh_token == "old-refresh"

    async def test_keeps_existing_refresh_token_when_response_has_none(self, service):
        svc, confluence, token = service
        confluence.refresh_access_token.return_value = {
            "access_token": "new-access",
            "refresh_token": None,
        }

        result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.refresh_token == "old-refresh"

    async def test_rotates_refresh_token_when_provided(self, service):
        svc, confluence, token = service
        confluence.refresh_access_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }

        result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.refresh_token == "new-refresh"
