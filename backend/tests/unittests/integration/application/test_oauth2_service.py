import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.application.oauth2_service import Oauth2Service
from eneo.integration.presentation.models import IntegrationType
from eneo.main.exceptions import BadRequestException


@pytest.fixture
def redis_client():
    client = AsyncMock()
    client.set = AsyncMock()
    client.getdel = AsyncMock(return_value=None)
    return client


@pytest.fixture
def service(redis_client):
    return Oauth2Service(
        confluence_auth_service=AsyncMock(),
        tenant_integration_repo=AsyncMock(),
        user_integration_repo=AsyncMock(),
        oauth_token_repo=AsyncMock(),
        sharepoint_auth_service=AsyncMock(),
        redis_client=redis_client,
    )


def _tenant_integration(tenant_integration_id):
    ti = MagicMock()
    ti.id = tenant_integration_id
    ti.integration_type = IntegrationType.Sharepoint.value
    ti.tenant_id = uuid4()
    return ti


class TestStartAuth:
    async def test_generates_and_stores_state(self, service, redis_client):
        ti_id = uuid4()
        user_id = uuid4()
        service.tenant_integration_repo.one.return_value = _tenant_integration(ti_id)
        service.sharepoint_auth_service.gen_auth_url = AsyncMock(
            return_value={"auth_url": "https://login.microsoftonline.com/authorize?..."}
        )

        result = await service.start_auth(tenant_integration_id=ti_id, user_id=user_id)

        assert result["auth_url"].startswith("https://login.microsoftonline.com")
        assert result["state"]
        # state was stored in Redis bound to this user + integration
        redis_client.set.assert_awaited_once()
        stored_payload = json.loads(redis_client.set.await_args.args[1])
        assert stored_payload == {
            "user_id": str(user_id),
            "tenant_integration_id": str(ti_id),
        }
        # the same state was passed to the provider auth-url builder
        assert (
            service.sharepoint_auth_service.gen_auth_url.await_args.args[0]
            == (result["state"])
        )


class TestAuthIntegrationCsrf:
    async def test_rejects_missing_or_expired_state(self, service, redis_client):
        redis_client.getdel.return_value = None

        with pytest.raises(BadRequestException):
            await service.auth_integration(
                user_id=uuid4(),
                tenant_integration_id=uuid4(),
                auth_code="code",
                state="unknown-state",
            )

    async def test_rejects_state_bound_to_other_user(self, service, redis_client):
        attacker_state_owner = uuid4()
        ti_id = uuid4()
        redis_client.getdel.return_value = json.dumps(
            {
                "user_id": str(attacker_state_owner),
                "tenant_integration_id": str(ti_id),
            }
        )

        with pytest.raises(BadRequestException):
            await service.auth_integration(
                user_id=uuid4(),  # different (victim) user
                tenant_integration_id=ti_id,
                auth_code="code",
                state="some-state",
            )
        # state is single-use even on rejection
        redis_client.getdel.assert_awaited_once()

    async def test_accepts_matching_state_and_proceeds(self, service, redis_client):
        user_id = uuid4()
        ti_id = uuid4()
        redis_client.getdel.return_value = json.dumps(
            {"user_id": str(user_id), "tenant_integration_id": str(ti_id)}
        )
        service.tenant_integration_repo.one.return_value = _tenant_integration(ti_id)
        service.user_integration_repo.one_or_none.return_value = None
        created = MagicMock()
        service.user_integration_repo.add.return_value = created

        with patch.object(service, "_fetch_token", AsyncMock()) as mock_fetch:
            result = await service.auth_integration(
                user_id=user_id,
                tenant_integration_id=ti_id,
                auth_code="code",
                state="valid-state",
            )

        assert result is created
        mock_fetch.assert_awaited_once()
