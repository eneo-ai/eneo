from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.integration.infrastructure import oauth_token_service as module
from eneo.integration.infrastructure.oauth_token_service import OauthTokenService
from eneo.main.container.container import Container

_REFRESH = "eneo.worker.redis.lease.LuaScripts.refresh_owned_lock"
_RELEASE = "eneo.worker.redis.lease.LuaScripts.release_owned_lock"


class _FakeRedis:
    """SET NX that is refused ``busy_rounds`` times, as if another worker held it."""

    def __init__(self, busy_rounds: int = 0) -> None:
        self.busy_rounds = busy_rounds
        self.keys: list[str] = []

    async def set(self, key: str, value: str, nx: bool, ex: int) -> bool | None:
        self.keys.append(key)
        if self.busy_rounds > 0:
            self.busy_rounds -= 1
            return None
        return True


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


def _leased_service(token, *, busy_rounds: int, fresh_access: str):
    repo = AsyncMock()
    repo.one.return_value = token
    fresh = MagicMock()
    fresh.access_token = fresh_access
    repo.one_fresh.return_value = fresh
    repo.update.side_effect = lambda obj: obj
    confluence = AsyncMock()
    confluence.refresh_access_token.return_value = {"access_token": "refreshed"}
    redis = _FakeRedis(busy_rounds=busy_rounds)
    svc = OauthTokenService(
        oauth_token_repo=repo,
        confluence_auth_service=confluence,
        sharepoint_auth_service=AsyncMock(),
        redis_client=redis,
    )
    return svc, repo, confluence, redis, fresh


class TestCrossWorkerRefreshLease:
    async def test_refresh_runs_under_a_lease_keyed_by_the_token(self, token):
        token_id = uuid4()
        svc, repo, confluence, redis, _ = _leased_service(
            token, busy_rounds=0, fresh_access="unused"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)) as release,
        ):
            result = await svc.refresh_and_update_token(token_id=token_id)

        assert result.access_token == "refreshed"
        assert redis.keys == [f"integration:oauth_token_refresh:{token_id}"]
        confluence.refresh_access_token.assert_awaited_once()
        repo.one_fresh.assert_not_awaited()
        release.assert_awaited_once()

    async def test_queued_caller_reuses_a_token_refreshed_meanwhile(
        self, token, monkeypatch
    ):
        monkeypatch.setattr(module, "_REFRESH_LEASE_POLL_SECONDS", 0.001)
        svc, repo, confluence, _, fresh = _leased_service(
            token, busy_rounds=2, fresh_access="refreshed-elsewhere"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result is fresh
        confluence.refresh_access_token.assert_not_awaited()
        repo.update.assert_not_awaited()

    async def test_queued_caller_refreshes_when_the_row_did_not_change(
        self, token, monkeypatch
    ):
        monkeypatch.setattr(module, "_REFRESH_LEASE_POLL_SECONDS", 0.001)
        svc, repo, confluence, _, _ = _leased_service(
            token, busy_rounds=1, fresh_access="old-access"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.access_token == "refreshed"
        confluence.refresh_access_token.assert_awaited_once()
        repo.update.assert_awaited_once()

    async def test_waiting_gives_up_after_the_deadline_and_refreshes(
        self, token, monkeypatch
    ):
        monkeypatch.setattr(module, "_REFRESH_LEASE_POLL_SECONDS", 0.001)
        monkeypatch.setattr(module, "_REFRESH_LEASE_WAIT_SECONDS", 0.0)
        svc, _, confluence, _, _ = _leased_service(
            token, busy_rounds=10**6, fresh_access="unused"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.access_token == "refreshed"
        confluence.refresh_access_token.assert_awaited_once()

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(RedisConnectionError("refused"), id="redis-error"),
            pytest.param(OSError("network down"), id="socket-error"),
        ],
    )
    async def test_redis_outage_still_refreshes_exactly_once(self, token, error):
        svc, repo, confluence, redis, _ = _leased_service(
            token, busy_rounds=0, fresh_access="unused"
        )
        redis.set = AsyncMock(side_effect=error)

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)) as release,
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result.access_token == "refreshed"
        confluence.refresh_access_token.assert_awaited_once()
        repo.update.assert_awaited_once()
        release.assert_not_awaited()

    def test_container_wires_the_redis_client(self):
        assert "redis_client" in Container.oauth_token_service.kwargs
