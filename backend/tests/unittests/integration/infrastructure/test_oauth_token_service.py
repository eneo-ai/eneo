import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

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
    repo.one_fresh.return_value = token
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

    async def test_the_process_lock_entry_is_dropped_once_no_caller_needs_it(
        self, service
    ):
        svc, confluence, token = service
        token_id = uuid4()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_refresh(refresh_token):
            entered.set()
            await release.wait()
            return {"access_token": "new-access"}

        confluence.refresh_access_token.side_effect = slow_refresh
        first = asyncio.create_task(svc.refresh_and_update_token(token_id=token_id))
        await entered.wait()
        second = asyncio.create_task(svc.refresh_and_update_token(token_id=token_id))
        await asyncio.sleep(0)

        lock, holders = OauthTokenService._refresh_locks[str(token_id)]
        assert lock.locked() and holders == 2
        release.set()
        await asyncio.gather(first, second)

        assert str(token_id) not in OauthTokenService._refresh_locks


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
            token, busy_rounds=0, fresh_access="old-access"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)) as release,
        ):
            result = await svc.refresh_and_update_token(token_id=token_id)

        assert result.access_token == "refreshed"
        assert redis.keys == [f"integration:oauth_token_refresh:{token_id}"]
        confluence.refresh_access_token.assert_awaited_once()
        repo.one_fresh.assert_awaited_once_with(token.id)
        release.assert_awaited_once()

    async def test_a_holder_that_did_not_wait_still_reuses_a_token_refreshed_meanwhile(
        self, token
    ):
        """The lease can be free again between this caller's read and its SET NX."""
        svc, repo, confluence, _, fresh = _leased_service(
            token, busy_rounds=0, fresh_access="refreshed-elsewhere"
        )

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result is fresh
        confluence.refresh_access_token.assert_not_awaited()
        repo.update.assert_not_awaited()

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
            token, busy_rounds=10**6, fresh_access="old-access"
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
            token, busy_rounds=0, fresh_access="old-access"
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

    @pytest.mark.parametrize("fallback", ["deadline", "redis-outage"])
    async def test_refreshing_without_the_lease_still_reuses_a_changed_row(
        self, token, monkeypatch, fallback
    ):
        monkeypatch.setattr(module, "_REFRESH_LEASE_POLL_SECONDS", 0.001)
        monkeypatch.setattr(module, "_REFRESH_LEASE_WAIT_SECONDS", 0.0)
        svc, repo, confluence, redis, fresh = _leased_service(
            token, busy_rounds=10**6, fresh_access="refreshed-elsewhere"
        )
        if fallback == "redis-outage":
            redis.set = AsyncMock(side_effect=RedisConnectionError("refused"))

        with (
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert result is fresh
        confluence.refresh_access_token.assert_not_awaited()
        repo.update.assert_not_awaited()

    def test_container_wires_the_redis_client_and_token_mapper(self):
        assert "redis_client" in Container.oauth_token_service.kwargs
        assert "token_mapper" in Container.oauth_token_service.kwargs


class _CommittedRow:
    """The oauth_tokens row as another connection reads it, plus the own
    connection the service writes it on; the caller's session is the mock
    repo and never reaches this store."""

    def __init__(self, *, fail: bool = False, lock_timeout: bool = False) -> None:
        self.values = {"access_token": "old-access", "refresh_token": "old-refresh"}
        self.fail = fail
        self.lock_timeout = lock_timeout
        self.writes = 0

    @asynccontextmanager
    async def session(self):
        if self.fail:
            raise RuntimeError("no connection")
        session = MagicMock()
        session.execute = AsyncMock(side_effect=self._execute)
        session.begin = asynccontextmanager(self._begin)
        yield session

    async def _begin(self):
        yield

    async def _execute(self, stmt):
        if not isinstance(stmt, sa.Update):
            return
        if self.lock_timeout:
            raise OperationalError("UPDATE", {}, Exception("lock timeout"))
        params = stmt.compile().params
        for column in ("access_token", "refresh_token"):
            self.values[column] = params[column].removeprefix("enc:")
        self.writes += 1

    def entity(self) -> MagicMock:
        entity = MagicMock()
        entity.access_token = self.values["access_token"]
        entity.refresh_token = self.values["refresh_token"]
        return entity


def _committing_service(row: _CommittedRow, token, *, busy_rounds: int):
    repo = AsyncMock()
    repo.one.return_value = token
    repo.one_fresh.side_effect = lambda id: row.entity()
    repo.update.side_effect = lambda obj: obj
    mapper = MagicMock()
    mapper.to_db_dict.side_effect = lambda t: {
        "access_token": f"enc:{t.access_token}",
        "refresh_token": f"enc:{t.refresh_token}",
    }
    confluence = AsyncMock()
    confluence.refresh_access_token.return_value = {
        "access_token": "refreshed",
        "refresh_token": "rotated",
    }
    svc = OauthTokenService(
        oauth_token_repo=repo,
        confluence_auth_service=confluence,
        sharepoint_auth_service=AsyncMock(),
        redis_client=_FakeRedis(busy_rounds=busy_rounds),
        token_mapper=mapper,
    )
    return svc, repo, confluence


class TestRefreshedTokenIsCommittedBeforeTheLeaseIsReleased:
    async def test_a_waiter_sees_the_rotation_while_the_holders_job_is_uncommitted(
        self, token, monkeypatch
    ):
        monkeypatch.setattr(module, "_REFRESH_LEASE_POLL_SECONDS", 0.001)
        token_id = uuid4()
        row = _CommittedRow()
        holder, holder_repo, holder_auth = _committing_service(
            row, token, busy_rounds=0
        )
        waiter_token = MagicMock(access_token="old-access", refresh_token="old-refresh")
        waiter_token.token_type.is_confluence = True
        waiter, waiter_repo, waiter_auth = _committing_service(
            row, waiter_token, busy_rounds=1
        )

        with (
            patch(f"{module.__name__}.sessionmanager", row),
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            held = await holder.refresh_and_update_token(token_id=token_id)
            waited = await waiter.refresh_and_update_token(token_id=token_id)

        assert (held.access_token, held.refresh_token) == ("refreshed", "rotated")
        assert row.values == {"access_token": "refreshed", "refresh_token": "rotated"}
        holder_repo.update.assert_not_awaited()
        # Once before refreshing (nobody else did), once after the own-connection write.
        assert holder_repo.one_fresh.await_count == 2
        assert (waited.access_token, waited.refresh_token) == ("refreshed", "rotated")
        waiter_auth.refresh_access_token.assert_not_awaited()
        waiter_repo.update.assert_not_awaited()

    @pytest.mark.parametrize(
        "row",
        [
            pytest.param(_CommittedRow(fail=True), id="no-connection"),
            pytest.param(_CommittedRow(lock_timeout=True), id="row-locked"),
        ],
    )
    async def test_write_falls_back_to_the_callers_transaction(self, token, row):
        svc, repo, _ = _committing_service(row, token, busy_rounds=0)

        with (
            patch(f"{module.__name__}.sessionmanager", row),
            patch(_REFRESH, new=AsyncMock(return_value=True)),
            patch(_RELEASE, new=AsyncMock(return_value=True)),
        ):
            result = await svc.refresh_and_update_token(token_id=uuid4())

        assert (result.access_token, result.refresh_token) == ("refreshed", "rotated")
        assert row.values["access_token"] == "old-access"
        repo.update.assert_awaited_once_with(obj=token)
        repo.one_fresh.assert_awaited_once_with(token.id)
