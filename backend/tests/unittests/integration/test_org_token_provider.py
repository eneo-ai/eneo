"""Organisation token acquisition records credential health on the tenant app."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from eneo.integration.domain.entities.tenant_sharepoint_app import (
    AUTH_METHOD_SERVICE_ACCOUNT,
    AUTH_METHOD_TENANT_APP,
    TenantSharePointApp,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
    OrgTokenProvider,
    SharePointCredentialsInvalidError,
    loggable_token_reason,
    summarize_token_endpoint_error,
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

    def __init__(self, *, fail: bool = False, lock_timeout: bool = False) -> None:
        self.fail = fail
        self.lock_timeout = lock_timeout
        self.statements: list[object] = []

    @asynccontextmanager
    async def session(self):
        if self.fail:
            raise RuntimeError("no connection")
        session = MagicMock()
        session.execute = AsyncMock(side_effect=self._execute)
        session.begin = asynccontextmanager(self._begin)
        yield session

    async def _execute(self, stmt):
        self.statements.append(stmt)
        if self.lock_timeout and isinstance(stmt, sa.Update):
            raise OperationalError(
                "UPDATE tenant_sharepoint_apps SET ...",
                {"service_account_refresh_token_encrypted": "enc:ciphertext"},
                Exception("canceling statement due to lock timeout"),
            )

    async def _begin(self):
        yield

    def updates(self) -> list[sa.Update]:
        return [stmt for stmt in self.statements if isinstance(stmt, sa.Update)]


def _provider(app_auth=None, account_auth=None, *, encryption=True):
    repo = AsyncMock()
    repo.update.side_effect = lambda obj: obj
    encryption_service = MagicMock()
    encryption_service.encrypt.side_effect = lambda value: f"enc:{value}"
    return (
        OrgTokenProvider(
            tenant_app_repo=repo,
            tenant_app_auth_service=app_auth or AsyncMock(),
            service_account_auth_service=account_auth or AsyncMock(),
            encryption_service=encryption_service if encryption else None,
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
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            assert await provider.get_access_token(app) == "at"

        assert app.auth_status == "ok"
        assert app.last_auth_error is None
        assert app.service_account_refresh_token == "refresh-2"
        (update,) = sessions.updates()
        written = update.compile().params
        assert written["service_account_refresh_token_encrypted"] == "enc:refresh-2"
        assert written["last_auth_error"] is None
        assert written["last_auth_success_at"] == app.last_auth_success_at
        repo.update.assert_not_awaited()

    @pytest.mark.parametrize(
        "previous, rotated, persisted",
        [
            pytest.param({}, False, True, id="first-success"),
            pytest.param(
                {"last_auth_success_at": _NOW - timedelta(minutes=1)},
                False,
                False,
                id="fresh-stamp",
            ),
            pytest.param(
                {"last_auth_success_at": _NOW - timedelta(minutes=1)},
                True,
                True,
                id="fresh-stamp-but-rotated",
            ),
        ],
    )
    async def test_service_account_success_writes_the_row_only_when_it_changes(
        self, previous, rotated, persisted
    ):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.return_value = {
            "access_token": "at",
            "refresh_token": "refresh-2" if rotated else "refresh-1",
        }
        provider, repo = _provider(account_auth=account_auth)
        app = _app(AUTH_METHOD_SERVICE_ACCOUNT, **previous)
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            assert await provider.get_access_token(app) == "at"

        assert app.auth_status == "ok"
        assert len(sessions.updates()) == (1 if persisted else 0)
        if rotated:
            (update,) = sessions.updates()
            params = update.compile().params
            assert params["service_account_refresh_token_encrypted"] == "enc:refresh-2"
        repo.update.assert_not_awaited()

    async def test_service_account_rotation_without_encryption_uses_the_callers_repo(
        self,
    ):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.return_value = {
            "access_token": "at",
            "refresh_token": "refresh-2",
        }
        provider, repo = _provider(account_auth=account_auth, encryption=False)
        app = _app(AUTH_METHOD_SERVICE_ACCOUNT)
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            assert await provider.get_access_token(app) == "at"

        assert sessions.statements == []
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
        sessions = _FakeSessionManager()

        with patch(f"{_MODULE}.sessionmanager", sessions):
            assert await provider.get_access_token(app, force_refresh=True) == "at"

        app_auth.get_access_token.assert_awaited_once_with(app, force_refresh=True)
        assert app.auth_status == "ok"
        assert len(sessions.updates()) == (1 if persisted else 0)
        repo.update.assert_not_awaited()

    async def test_success_write_falls_back_to_the_callers_transaction_on_lock_timeout(
        self,
    ):
        app_auth = AsyncMock()
        app_auth.get_access_token.return_value = "at"
        provider, repo = _provider(app_auth=app_auth)
        app = _app()
        sessions = _FakeSessionManager(lock_timeout=True)

        with (
            patch(f"{_MODULE}.sessionmanager", sessions),
            patch(f"{_MODULE}.logger") as log,
        ):
            assert await provider.get_access_token(app) == "at"

        assert len(sessions.updates()) == 1
        assert app.auth_status == "ok"
        repo.update.assert_awaited_once_with(app)
        logged = [
            str(call.args[0]) % call.args[1:] for call in log.warning.call_args_list
        ]
        assert logged and all("enc:ciphertext" not in line for line in logged)

    async def test_failed_success_write_does_not_fail_the_acquisition(self):
        account_auth = AsyncMock()
        account_auth.refresh_access_token.return_value = {
            "access_token": "at",
            "refresh_token": "refresh-2",
        }
        provider, repo = _provider(account_auth=account_auth, encryption=False)
        repo.update.side_effect = RuntimeError("connection lost")
        app = _app(AUTH_METHOD_SERVICE_ACCOUNT)

        assert await provider.get_access_token(app) == "at"

        assert app.service_account_refresh_token == "refresh-2"
        repo.update.assert_awaited_once_with(app)


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
            pytest.param(
                400,
                {
                    "error": "invalid_scope",
                    "error_description": "AADSTS70011: scope is not valid",
                },
                "AADSTS70011: scope is not valid",
                id="invalid_scope",
            ),
            pytest.param(
                400,
                {
                    "error": "invalid_resource",
                    "error_description": "AADSTS500011: resource principal not found",
                },
                "AADSTS500011: resource principal not found",
                id="invalid_resource",
            ),
            pytest.param(
                400,
                {
                    "error": "invalid_request",
                    "error_description": "AADSTS90002: Tenant 'contsoo' not found.",
                },
                "AADSTS90002: Tenant 'contsoo' not found.",
                id="invalid_request-tenant-not-found",
            ),
            pytest.param(
                400,
                {
                    "error": "invalid_request",
                    "error_description": "AADSTS700016: Application with identifier 'x' was not found",
                },
                "AADSTS700016: Application with identifier 'x' was not found",
                id="invalid_request-application-not-found",
            ),
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

    @pytest.mark.parametrize(
        "sessions",
        [
            pytest.param(_FakeSessionManager(fail=True), id="no-connection"),
            pytest.param(_FakeSessionManager(lock_timeout=True), id="lock-timeout"),
        ],
    )
    async def test_failure_write_falls_back_to_the_callers_transaction(self, sessions):
        app_auth = AsyncMock()
        app_auth.get_access_token.side_effect = _token_error(
            400, {"error": "invalid_client"}
        )
        provider, repo = _provider(app_auth=app_auth)
        app = _app()

        with patch(f"{_MODULE}.sessionmanager", sessions):
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
            pytest.param(
                _token_error(
                    400,
                    {
                        "error": "invalid_request",
                        "error_description": "AADSTS900144: The request body must contain the following parameter: 'grant_type'.",
                    },
                ),
                id="invalid_request-malformed-call",
            ),
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

        with patch(f"{_MODULE}.sessionmanager", _FakeSessionManager()):
            assert await provider.test_connection(app) == (True, None)
        assert app.auth_status == "ok"


@pytest.mark.parametrize(
    "auth_method", [AUTH_METHOD_TENANT_APP, AUTH_METHOD_SERVICE_ACCOUNT]
)
async def test_access_token_provider_forces_a_fresh_token(auth_method):
    app_auth = AsyncMock()
    app_auth.get_access_token.return_value = "fresh"
    account_auth = AsyncMock()
    account_auth.refresh_access_token.return_value = {"access_token": "fresh"}
    provider, _ = _provider(app_auth=app_auth, account_auth=account_auth)
    app = _app(auth_method, last_auth_success_at=_NOW)

    with patch(f"{_MODULE}.sessionmanager", _FakeSessionManager()):
        assert await provider.access_token_provider(app)() == "fresh"
    if auth_method == AUTH_METHOD_SERVICE_ACCOUNT:
        account_auth.refresh_access_token.assert_awaited_once_with(
            app, force_refresh=True
        )
    else:
        app_auth.get_access_token.assert_awaited_once_with(app, force_refresh=True)


@pytest.mark.parametrize(
    "description",
    [
        "AADSTS70008: The code has expired.\r\nTrace ID: 1f\r\nCorrelation ID: 2e",
        "AADSTS70008: The code has expired.\nTrace ID: 1f\nCorrelation ID: 2e",
        "AADSTS70008: The code has expired. Trace ID: 1f Correlation ID: 2e "
        "Timestamp: 2026-10-19 12:00:00Z",
        "AADSTS70008: The code has expired. Timestamp: 2026-10-19 12:00:00Z",
    ],
    ids=["crlf", "lf", "one-line", "timestamp-only"],
)
def test_the_summary_drops_microsofts_trace_lines_however_they_are_separated(
    description,
):
    error = _token_error(
        400, {"error": "invalid_grant", "error_description": description}
    )

    assert summarize_token_endpoint_error(error) == (
        "AADSTS70008: The code has expired."
    )


@pytest.mark.parametrize(
    "reason, logged",
    [
        (
            _token_error(
                401,
                {
                    "error": "invalid_client",
                    "error_description": "AADSTS7000215: Invalid client secret "
                    "provided for app '11111111-2222-3333-4444-555555555555'.",
                },
            ),
            "invalid_client AADSTS7000215",
        ),
        (
            "AADSTS50034: The user account anna.svensson@sundsvall.se does not "
            "exist in the 1a2b3c4d-0000-1111-2222-333344445555 directory.",
            "AADSTS50034",
        ),
        ("invalid_grant", "invalid_grant"),
        ("HTTP 401", "HTTP 401"),
        ("The account anna.svensson@sundsvall.se is disabled", "unrecognized reason"),
    ],
    ids=["refusal", "stored-detail", "error-only", "status-only", "free-text"],
)
def test_a_refusal_is_logged_by_its_codes_only(reason, logged):
    """Descriptions can name accounts and directories."""
    assert loggable_token_reason(reason) == logged


async def test_a_recorded_refusal_logs_no_description():
    app_auth = AsyncMock()
    app_auth.get_access_token.side_effect = _token_error(
        401,
        {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided "
            "for app '11111111-2222-3333-4444-555555555555'.",
        },
    )
    provider, _ = _provider(app_auth=app_auth)

    with (
        patch(f"{_MODULE}.sessionmanager", _FakeSessionManager()),
        patch(f"{_MODULE}.logger") as log,
    ):
        with pytest.raises(SharePointCredentialsInvalidError):
            await provider.get_access_token(_app())

    logged = " ".join(
        str(call.args[0]) % call.args[1:] for call in log.warning.call_args_list
    )
    assert "AADSTS7000215" in logged
    assert "11111111-2222-3333-4444-555555555555" not in logged
