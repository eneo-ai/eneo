"""Password-login responses and structured logs must never echo credentials."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from eneo.audit.infrastructure.rate_limiting import RateLimitServiceUnavailableError
from eneo.authentication.auth_models import AccessToken
from eneo.authentication.auth_service import AuthService
from eneo.authentication.login_attempts import LoginAttempt
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuthenticationException,
    ErrorCodes,
    QuotaExceededException,
)
from eneo.main.logging import OTELJSONFormatter, SimpleLogger
from eneo.main.models import GeneralError
from eneo.server.endpoint_routes import endpoint_routes
from eneo.server.main import get_application
from eneo.tenants.tenant import TenantState
from eneo.users import user_router
from eneo.users.user import UserState
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER

LOGIN_PATH = "/api/v1/users/login/token/"
EMAIL = "login@example.com"
PASSWORD = "LoginCredential-SENTINEL-123!"
TOKEN = AccessToken(access_token="issued-token", token_type="bearer")


@dataclass
class LoginEndpoint:
    client: TestClient
    service: AsyncMock
    count: AsyncMock
    clear: AsyncMock


@pytest.fixture
def login_endpoint(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[LoginEndpoint]:
    service = AsyncMock(spec=UserService)
    service.login.return_value = TOKEN
    count = AsyncMock(return_value=LoginAttempt(True, 4, 600))
    clear = AsyncMock()
    monkeypatch.setattr(user_router, "count_login_attempt", count)
    monkeypatch.setattr(user_router, "clear_login_attempts", clear)

    container = Container(
        user_service=providers.Object(service),
        redis_client=providers.Object(object()),
    )
    app = get_application()
    route = next(
        route for route in endpoint_routes(app.routes) if route.path == LOGIN_PATH
    )
    assert route.dependant is not None
    dependency = next(
        dependency
        for dependency in route.dependant.dependencies
        if dependency.name == "container"
    )

    def login_container() -> Container:
        return container

    app.dependency_overrides[dependency.call] = login_container
    # SimpleLogger has its own handler; capture its extras, not just log text.
    user_router.logger.addHandler(caplog.handler)
    client = TestClient(app)
    try:
        yield LoginEndpoint(client, service, count, clear)
    finally:
        client.close()
        user_router.logger.removeHandler(caplog.handler)


def structured_logs(caplog: pytest.LogCaptureFixture) -> str:
    formatter = OTELJSONFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


def login_log(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    return next(record for record in caplog.records if record.getMessage() == message)


def validation_errors(response) -> list[dict[str, object]]:
    error = GeneralError.model_validate(response.json())
    assert error.code == "request_validation_error"
    assert error.eneo_error_code == ErrorCodes.VALIDATION_ERROR
    return response.json()["details"]["errors"]


def logged_correlation_ids(caplog: pytest.LogCaptureFixture) -> set[str]:
    return {
        record.correlation_id  # type: ignore[attr-defined]
        for record in caplog.records
        if hasattr(record, "correlation_id")
    }


@pytest.mark.parametrize(
    ("username", "password", "form_field", "error_type"),
    [
        (EMAIL, "s3cret", "password", "string_too_short"),
        (EMAIL, "s" * 101, "password", "string_too_long"),
        (EMAIL, "密" * 101, "password", "string_too_long"),
        ("invalid-email-SENTINEL", PASSWORD, "username", "value_error"),
    ],
)
def test_invalid_login_uses_safe_public_validation_errors(
    login_endpoint: LoginEndpoint,
    caplog: pytest.LogCaptureFixture,
    username: str,
    password: str,
    form_field: str,
    error_type: str,
) -> None:
    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": username, "password": password}
    )

    assert response.status_code == 422
    # Same location shape as FastAPI's own form errors for this endpoint.
    assert validation_errors(response) == [
        {
            "location": ["body", form_field],
            "type": error_type,
            "message": "Invalid value",
        }
    ]
    assert response.headers["X-Correlation-ID"]
    assert password not in response.text
    assert password not in structured_logs(caplog)
    if form_field == "username":
        assert username not in response.text
        assert username not in structured_logs(caplog)
    login_endpoint.count.assert_not_awaited()
    login_endpoint.service.login.assert_not_awaited()


def test_missing_form_field_and_manual_validation_report_locations_alike(
    login_endpoint: LoginEndpoint,
) -> None:
    missing = login_endpoint.client.post(LOGIN_PATH, data={"username": EMAIL})
    malformed = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": "short"}
    )

    assert [error["location"] for error in validation_errors(missing)] == [
        ["body", "password"]
    ]
    assert [error["location"] for error in validation_errors(malformed)] == [
        ["body", "password"]
    ]


@pytest.mark.parametrize(
    ("password", "expected_status"),
    [("short", 422), (PASSWORD, 401), ("Unexpected-" + PASSWORD, 500)],
)
@pytest.mark.parametrize("tracing", [True, False], ids=["traced", "untraced"])
def test_correlation_header_names_the_id_in_the_login_logs(
    login_endpoint: LoginEndpoint,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    password: str,
    expected_status: int,
    tracing: bool,
) -> None:
    """Support reads the header and searches the logs for it; the caller's own
    id is still echoed as ``request_id`` in the body, as documented."""
    if not tracing:
        for target in (
            "eneo.server.middleware.trace_id.current_trace_id",
            "eneo.server.middleware.request_context._current_trace_id",
            "eneo.server.main.current_trace_id",
        ):
            monkeypatch.setattr(target, lambda: None)
    login_endpoint.service.login.side_effect = (
        RuntimeError("boom") if expected_status == 500 else AuthenticationException()
    )

    response = login_endpoint.client.post(
        LOGIN_PATH,
        data={"username": EMAIL, "password": password},
        headers={"X-Correlation-ID": "caller-supplied-id"},
    )

    assert response.status_code == expected_status
    header = response.headers["X-Correlation-ID"]
    assert logged_correlation_ids(caplog) == {header}
    if expected_status != 422:
        assert response.json()["request_id"] == "caller-supplied-id"


@pytest.mark.parametrize(
    "data",
    [
        {"password": PASSWORD},
        {"username": EMAIL},
        {"username": EMAIL, "password": PASSWORD, "grant_type": PASSWORD},
    ],
)
def test_form_validation_never_echoes_credentials(
    login_endpoint: LoginEndpoint,
    caplog: pytest.LogCaptureFixture,
    data: dict[str, str],
) -> None:
    response = login_endpoint.client.post(LOGIN_PATH, data=data)

    assert response.status_code == 422
    assert all(
        set(error) == {"location", "type", "message"}
        for error in validation_errors(response)
    )
    assert PASSWORD not in response.text
    assert PASSWORD not in structured_logs(caplog)
    login_endpoint.count.assert_not_awaited()
    login_endpoint.service.login.assert_not_awaited()


def test_json_is_not_accepted_as_a_password_login_form(
    login_endpoint: LoginEndpoint, caplog: pytest.LogCaptureFixture
) -> None:
    response = login_endpoint.client.post(
        LOGIN_PATH, json={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert PASSWORD not in structured_logs(caplog)
    login_endpoint.service.login.assert_not_awaited()


def test_multipart_file_cannot_bypass_safe_form_validation(
    login_endpoint: LoginEndpoint, caplog: pytest.LogCaptureFixture
) -> None:
    response = login_endpoint.client.post(
        LOGIN_PATH,
        data={"username": EMAIL},
        files={"password": ("credential.txt", PASSWORD)},
    )

    assert response.status_code == 422
    assert all(
        set(error) == {"location", "type", "message"}
        for error in validation_errors(response)
    )
    assert PASSWORD not in response.text
    assert PASSWORD not in structured_logs(caplog)
    login_endpoint.service.login.assert_not_awaited()


def test_manual_validation_keeps_correlation_header_without_tracing(
    login_endpoint: LoginEndpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "eneo.server.middleware.trace_id.current_trace_id", lambda: None
    )
    monkeypatch.setattr(
        "eneo.server.middleware.request_context._current_trace_id", lambda: None
    )

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": "short"}
    )

    assert response.status_code == 422
    assert response.headers["X-Correlation-ID"]


def test_invalid_credentials_keep_the_public_contract_without_exception_values(
    login_endpoint: LoginEndpoint, caplog: pytest.LogCaptureFixture
) -> None:
    login_endpoint.service.login.side_effect = AuthenticationException(PASSWORD)

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 401
    error = GeneralError.model_validate(response.json())
    assert error.code == "invalid_credentials"
    assert error.eneo_error_code == ErrorCodes.AUTHENTICATION_ERROR
    assert error.message == "Invalid credentials"
    assert response.json()["attempts_remaining"] == 4
    assert response.headers["X-Correlation-ID"]
    assert PASSWORD not in response.text
    assert PASSWORD not in structured_logs(caplog)
    login_endpoint.clear.assert_not_awaited()


@pytest.mark.parametrize(
    ("user_state", "tenant_state", "code"),
    [
        (UserState.INACTIVE, TenantState.ACTIVE, ErrorCodes.USER_INACTIVE),
        (UserState.ACTIVE, TenantState.SUSPENDED, ErrorCodes.TENANT_SUSPENDED),
    ],
)
@pytest.mark.parametrize("password_matches", [True, False])
def test_account_state_is_only_disclosed_after_password_verification(
    login_endpoint: LoginEndpoint,
    caplog: pytest.LogCaptureFixture,
    user_state: UserState,
    tenant_state: TenantState,
    code: ErrorCodes,
    password_matches: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "eneo.server.middleware.trace_id.current_trace_id", lambda: None
    )
    repo = AsyncMock()
    repo.get_user_by_email.return_value = TEST_USER.model_copy(
        update={
            "state": user_state,
            "password": "stored-password-hash",
            "tenant": TEST_TENANT.model_copy(update={"state": tenant_state}),
        }
    )
    auth = MagicMock(spec=AuthService)
    auth.verify_password.return_value = password_matches
    service = UserService(
        user_repo=repo,
        auth_service=auth,
        api_key_auth_resolver=AsyncMock(),
        api_key_v2_repo=AsyncMock(),
        audit_service=AsyncMock(),
        settings_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        info_blob_repo=AsyncMock(),
    )
    login_endpoint.service.login.side_effect = service.login

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == (403 if password_matches else 401)
    error = GeneralError.model_validate(response.json())
    assert response.headers["X-Correlation-ID"]
    if password_matches:
        assert error.eneo_error_code == code
        # Valid credentials against a blocked account are worth tracing.
        refused = login_log(caplog, "Login refused after credential verification")
        assert refused.levelno == logging.WARNING
        assert refused.email == EMAIL  # type: ignore[attr-defined]
        assert refused.source_ip  # type: ignore[attr-defined]
        assert refused.error_type in {  # type: ignore[attr-defined]
            "UserInactiveException",
            "TenantSuspendedException",
        }
    else:
        assert error.code == "invalid_credentials"
        assert error.message == "Invalid credentials"
    assert "access_token" not in response.json()
    login_endpoint.clear.assert_not_awaited()


def test_any_denial_with_a_registered_handler_keeps_its_canonical_response(
    login_endpoint: LoginEndpoint, caplog: pytest.LogCaptureFixture
) -> None:
    """Not only the two account-state denials: whatever the shared handlers
    answer canonically must not be downgraded to ``login_unavailable``."""
    login_endpoint.service.login.side_effect = QuotaExceededException(
        "Seat limit reached"
    )

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 403
    error = GeneralError.model_validate(response.json())
    assert error.eneo_error_code == ErrorCodes.QUOTA_EXCEEDED
    assert error.code != "login_unavailable"
    refused = login_log(caplog, "Login refused after credential verification")
    assert refused.error_type == "QuotaExceededException"  # type: ignore[attr-defined]
    login_endpoint.clear.assert_not_awaited()


def test_unexpected_errors_keep_diagnostics_with_the_password_redacted(
    login_endpoint: LoginEndpoint, caplog: pytest.LogCaptureFixture
) -> None:
    exception = RuntimeError(f"Backend failed with credential {PASSWORD}")
    exception.__cause__ = ValueError(f"Inner exception: {PASSWORD}")
    login_endpoint.service.login.side_effect = exception

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 500
    error = GeneralError.model_validate(response.json())
    assert error.eneo_error_code == ErrorCodes.INTERNAL_SERVER_ERROR
    # The shared 500 envelope: a generic message and the support error_id.
    assert error.code == "internal_error"
    assert error.error_id
    assert response.headers["X-Correlation-ID"]
    assert PASSWORD not in response.text
    logs = structured_logs(caplog)
    assert PASSWORD not in logs
    failure = next(
        record for record in caplog.records if record.levelno == logging.ERROR
    )
    assert failure.error_type == "RuntimeError"  # type: ignore[attr-defined]
    assert failure.error == "Backend failed with credential [REDACTED]"  # type: ignore[attr-defined]
    trace = failure.traceback  # type: ignore[attr-defined]
    assert "ValueError: Inner exception: [REDACTED]" in trace
    assert "RuntimeError: Backend failed with credential [REDACTED]" in trace
    assert "user_router.py" in trace
    plain_text = logging.Formatter(SimpleLogger.FORMAT_STRING).format(failure)
    assert "Login failed: unexpected error" in plain_text
    assert "ValueError: Inner exception: [REDACTED]" in plain_text
    assert "RuntimeError: Backend failed with credential [REDACTED]" in plain_text
    assert "user_router.py" in plain_text
    assert PASSWORD not in plain_text
    login_endpoint.clear.assert_not_awaited()


def test_throttled_login_keeps_retry_metadata_and_does_not_check_password(
    login_endpoint: LoginEndpoint,
) -> None:
    login_endpoint.count.return_value = LoginAttempt(False, 0, 123)

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 429
    assert (
        GeneralError.model_validate(response.json()).code == "too_many_login_attempts"
    )
    assert response.json()["attempts_remaining"] == 0
    assert response.json()["retry_after_seconds"] == 123
    assert response.headers["Retry-After"] == "123"
    login_endpoint.service.login.assert_not_awaited()
    login_endpoint.clear.assert_not_awaited()


def test_last_failed_attempt_keeps_the_waiting_time(
    login_endpoint: LoginEndpoint,
) -> None:
    login_endpoint.count.return_value = LoginAttempt(True, 0, 123)
    login_endpoint.service.login.side_effect = AuthenticationException()

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["attempts_remaining"] == 0
    assert response.json()["retry_after_seconds"] == 123


@pytest.mark.parametrize("limiter_failure", [None, "count", "clear"])
def test_success_preserves_the_token_and_recovers_from_limiter_outages(
    login_endpoint: LoginEndpoint,
    caplog: pytest.LogCaptureFixture,
    limiter_failure: str | None,
) -> None:
    if limiter_failure == "count":
        login_endpoint.count.side_effect = RateLimitServiceUnavailableError(
            RuntimeError(PASSWORD)
        )
    elif limiter_failure == "clear":
        login_endpoint.clear.side_effect = RateLimitServiceUnavailableError(
            RuntimeError(PASSWORD)
        )

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json() == TOKEN.model_dump()
    assert PASSWORD not in structured_logs(caplog)
    if limiter_failure == "count":
        login_endpoint.clear.assert_not_awaited()
    else:
        login_endpoint.clear.assert_awaited_once()


def test_failed_login_during_limiter_outage_omits_unknown_attempt_counts(
    login_endpoint: LoginEndpoint,
) -> None:
    login_endpoint.count.side_effect = RateLimitServiceUnavailableError(
        RuntimeError("Redis unavailable")
    )
    login_endpoint.service.login.side_effect = AuthenticationException()

    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert "attempts_remaining" not in response.json()
    assert "retry_after_seconds" not in response.json()


@pytest.mark.parametrize("password", ["1234567", "p" * 100])
def test_existing_password_length_boundaries_still_reach_authentication(
    login_endpoint: LoginEndpoint, password: str
) -> None:
    response = login_endpoint.client.post(
        LOGIN_PATH, data={"username": EMAIL, "password": password}
    )

    assert response.status_code == 200
    assert response.json() == TOKEN.model_dump()
