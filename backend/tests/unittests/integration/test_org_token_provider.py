"""Organisation token acquisition records credential health on the tenant app."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from eneo.integration.domain.entities.tenant_sharepoint_app import (
    AUTH_METHOD_SERVICE_ACCOUNT,
    AUTH_METHOD_TENANT_APP,
    TenantSharePointApp,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
    OrgTokenProvider,
    SharePointCredentialsInvalidError,
)

_MODULE = "eneo.integration.infrastructure.auth_service.org_token_provider"
_NOW = datetime.now(timezone.utc)


def _app(auth_method: str = AUTH_METHOD_TENANT_APP, **overrides) -> TenantSharePointApp:
    fields = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client",
        client_secret="secret",
        tenant_domain="contoso.onmicrosoft.com",
        auth_method=auth_method,
        service_account_refresh_token="refresh-1"
        if auth_method == AUTH_METHOD_SERVICE_ACCOUNT
        else None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    fields.update(overrides)
    return TenantSharePointApp(**fields)


def _token_error(status: int, body: dict[str, str]) -> httpx.HTTPStatusError:
    request = httpx.Request(
        "POST", "https://login.microsoftonline.com/x/oauth2/v2.0/token"
    )
    response = httpx.Response(status, request=request, content=json.dumps(body))
    return httpx.HTTPStatusError("refused", request=request, response=response)


class _FakeSessionManager:
    """Stands in for the database session manager used by the health writer."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.statements: list[object] = []

    @asynccontextmanager
    async def session(self):
        if self.fail:
            raise RuntimeError("no connection")
        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=lambda stmt: self.statements.append(stmt)
        )
        session.begin = asynccontextmanager(self._begin)
        yield session

    async def _begin(self):
        yield


def _provider(app_auth=None, account_auth=None):
    repo = AsyncMock()
    repo.update.side_effect = lambda obj: obj
    return (
        OrgTokenProvider(
            tenant_app_repo=repo,
            tenant_app_auth_service=app_auth or AsyncMock(),
            service_account_auth_service=account_auth or AsyncMock(),
        ),
        repo,
    )


class TestSuccess:
    async def test_service_account_round_trip_marks_ok_and_persists_rotation(self):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.return_value = {
            "access_token": "at",
            "refresh_token": "refresh-2",
        }
        provider, repo = _provider(account_auth=account_auth)
        app = _app(
            AUTH_METHOD_SERVICE_ACCOUNT, last_auth_error="old", last_auth_error_at=_NOW
        )

        assert await provider.get_access_token(app) == "at"

        assert app.auth_status == "ok"
        assert app.last_auth_error is None
        assert app.service_account_refresh_token == "refresh-2"
        repo.update.assert_awaited_once_with(app)

    @pytest.mark.parametrize(
        "previous, persisted",
        [
            pytest.param({}, True, id="first-success"),
            pytest.param(
                {"last_auth_error": "x", "last_auth_error_at": _NOW},
                True,
                id="recovered",
            ),
            pytest.param(
                {"last_auth_success_at": _NOW - timedelta(hours=1)},
                True,
                id="stale-stamp",
            ),
            pytest.param(
                {"last_auth_success_at": _NOW - timedelta(minutes=1)},
                False,
                id="fresh-stamp",
            ),
        ],
    )
    async def test_tenant_app_success_writes_the_row_only_when_it_changes(
        self, previous, persisted
    ):
        app_auth = AsyncMock()
        app_auth.get_access_token.return_value = "at"
        provider, repo = _provider(app_auth=app_auth)
        app = _app(**previous)

        assert await provider.get_access_token(app, force_refresh=True) == "at"

        app_auth.get_access_token.assert_awaited_once_with(app, force_refresh=True)
        assert app.auth_status == "ok"
        assert repo.update.await_count == (1 if persisted else 0)


class TestFailure:
    @pytest.mark.parametrize(
        "status, body, detail",
        [
            pytest.param(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "AADSTS70000: refresh token expired. Trace ID: abc\r\nCorrelation ID: def",
                },
                "AADSTS70000: refresh token expired.",
                id="invalid_grant",
            ),
            pytest.param(
                401,
                {
                    "error": "invalid_client",
                    "error_description": "AADSTS7000215: bad secret",
                },
                "AADSTS7000215: bad secret",
                id="invalid_client",
            ),
            pytest.param(
                400,
                {"error": "interaction_required"},
                "interaction_required",
                id="interaction_required",
            ),
            pytest.param(401, {}, "HTTP 401", id="bare-401"),
        ],
    )
    async def test_credential_refusal_is_recorded_on_its_own_connection(
        self, status, body, detail
    ):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.side_effect = _token_error(status, body)
        provider, repo = _provider(account_auth=account_auth)
        app = _app(
            AUTH_METHOD_SERVICE_ACCOUNT, last_auth_success_at=_NOW - timedelta(days=1)
        )
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            with pytest.raises(SharePointCredentialsInvalidError) as exc_info:
                await provider.get_access_token(app)

        assert str(exc_info.value) == CREDENTIALS_INVALID_MESSAGE
        assert exc_info.value.detail == detail
        assert app.auth_status == "error"
        assert app.last_auth_error == detail
        update = sessions.statements[-1]
        assert isinstance(update, sa.Update)
        assert update.table.name == "tenant_sharepoint_apps"
        repo.update.assert_not_awaited()

    async def test_failure_write_falls_back_to_the_callers_transaction(self):
        app_auth = AsyncMock()
        app_auth.get_access_token.side_effect = _token_error(
            400, {"error": "invalid_client"}
        )
        provider, repo = _provider(app_auth=app_auth)
        app = _app()

        with patch(f"{_MODULE}.sessionmanager", _FakeSessionManager(fail=True)):
            with pytest.raises(SharePointCredentialsInvalidError):
                await provider.get_access_token(app)

        assert app.auth_status == "error"
        repo.update.assert_awaited_once_with(app)

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(
                _token_error(503, {"error": "temporarily_unavailable"}), id="5xx"
            ),
            pytest.param(httpx.ConnectTimeout("slow"), id="timeout"),
        ],
    )
    async def test_transient_failures_are_not_credential_failures(self, error):
        app_auth = AsyncMock()
        app_auth.get_access_token.side_effect = error
        provider, repo = _provider(app_auth=app_auth)
        app = _app(last_auth_success_at=_NOW)
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            with pytest.raises(type(error)):
                await provider.get_access_token(app)

        assert app.auth_status == "ok"
        assert sessions.statements == []
        repo.update.assert_not_awaited()


class TestTestConnection:
    async def test_reports_refusal_detail_without_raising(self):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.side_effect = _token_error(
            400, {"error": "invalid_grant", "error_description": "AADSTS50173: revoked"}
        )
        provider, _ = _provider(account_auth=account_auth)
        app = _app(AUTH_METHOD_SERVICE_ACCOUNT)

        with patch(f"{_MODULE}.sessionmanager", _FakeSessionManager()):
            assert await provider.test_connection(app) == (
                False,
                "AADSTS50173: revoked",
            )
        assert app.auth_status == "error"

    async def test_reports_success(self):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.return_value = {"access_token": "at"}
        provider, _ = _provider(account_auth=account_auth)
        app = _app(AUTH_METHOD_SERVICE_ACCOUNT)

        assert await provider.test_connection(app) == (True, None)
        assert app.auth_status == "ok"


async def test_access_token_provider_forces_a_fresh_token():
    app_auth = AsyncMock()
    app_auth.get_access_token.return_value = "fresh"
    provider, _ = _provider(app_auth=app_auth)
    app = _app(last_auth_success_at=_NOW)

    assert await provider.access_token_provider(app)() == "fresh"
    app_auth.get_access_token.assert_awaited_once_with(app, force_refresh=True)
