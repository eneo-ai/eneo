from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import bcrypt
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from eneo.audit.domain.action_types import ActionType
from eneo.audit.infrastructure.rate_limiting import (
    RateLimitExceededError,
    RateLimitResult,
    RateLimitServiceUnavailableError,
)
from eneo.authentication.auth_dependencies import require_session_auth
from eneo.authentication.auth_service import JWT_ISSUER, AuthService
from eneo.main.exceptions import AuthenticationException, ErrorCodes
from eneo.server.exception_handlers import DOMAIN_EXCEPTION_MAP
from eneo.users import user_router
from eneo.users.password import (
    CurrentPasswordIncorrectError,
    LocalPasswordChangeUnavailableError,
    PasswordPolicyViolationError,
    PasswordReuseError,
    validate_new_local_password,
)
from eneo.users.user import PasswordChangeRequest, UserUpdatePublic
from eneo.users.user_repo import UsersRepository
from eneo.users.user_service import UserService
from tests.fixtures import TEST_USER

VALID_PASSWORD = "correct horse battery staple"


@pytest.fixture(name="service")
def service_with_mocks() -> UserService:
    return UserService(
        user_repo=AsyncMock(),
        auth_service=MagicMock(spec=AuthService),
        api_key_auth_resolver=AsyncMock(),
        api_key_v2_repo=AsyncMock(),
        audit_service=AsyncMock(),
        settings_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        info_blob_repo=AsyncMock(),
    )


def local_user(*, version: int = 0, password: str | None = "old-hash"):
    return TEST_USER.model_copy(
        update={"password": password, "credential_version": version}
    )


def test_local_password_policy_uses_character_minimum_and_utf8_byte_maximum():
    with pytest.raises(PasswordPolicyViolationError) as too_short:
        validate_new_local_password("short-password")
    assert too_short.value.details == {"rule": "min_length", "min_length": 15}

    validate_new_local_password("å" * 36)
    with pytest.raises(PasswordPolicyViolationError) as too_large:
        validate_new_local_password("å" * 37)
    assert too_large.value.details == {
        "rule": "max_bytes",
        "max_bytes": 72,
        "actual_bytes": 74,
    }


async def test_change_local_password_verifies_hashes_and_increments_version(
    service: UserService,
):
    user = local_user(version=4)
    updated = local_user(version=5, password="new-hash")
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = updated
    service.auth_service.verify_password.side_effect = [True, False]
    service.auth_service.create_salt_and_hashed_password.return_value = (
        "new-salt",
        "new-hash",
    )

    result = await service.change_local_password(
        user_id=user.id,
        current_password="the current password",
        new_password=VALID_PASSWORD,
    )

    assert result == updated
    service.repo.get_user_by_id_for_update.assert_awaited_once_with(user.id)
    update = service.repo.update.await_args.args[0]
    assert update.password == "new-hash"
    assert update.salt == "new-salt"
    assert update.credential_version == 5
    assert "the current password" not in repr(update)
    assert VALID_PASSWORD not in repr(update)


async def test_change_local_password_rejects_wrong_current_before_hashing(
    service: UserService,
):
    user = local_user()
    service.repo.get_user_by_id_for_update.return_value = user
    service.auth_service.verify_password.return_value = False

    with pytest.raises(CurrentPasswordIncorrectError):
        await service.change_local_password(
            user_id=user.id,
            current_password="wrong password",
            new_password=VALID_PASSWORD,
        )

    service.auth_service.create_salt_and_hashed_password.assert_not_called()
    service.repo.update.assert_not_awaited()


async def test_change_local_password_rejects_account_without_local_hash(
    service: UserService,
):
    user = local_user(password=None)
    service.repo.get_user_by_id_for_update.return_value = user

    with pytest.raises(LocalPasswordChangeUnavailableError):
        await service.change_local_password(
            user_id=user.id,
            current_password="irrelevant",
            new_password=VALID_PASSWORD,
        )

    service.auth_service.verify_password.assert_not_called()
    service.repo.update.assert_not_awaited()


async def test_change_local_password_rejects_reuse(service: UserService):
    user = local_user()
    service.repo.get_user_by_id_for_update.return_value = user
    service.auth_service.verify_password.side_effect = [True, True]

    with pytest.raises(PasswordReuseError):
        await service.change_local_password(
            user_id=user.id,
            current_password="same password",
            new_password=VALID_PASSWORD,
        )

    service.auth_service.create_salt_and_hashed_password.assert_not_called()
    service.repo.update.assert_not_awaited()


async def test_admin_password_update_uses_same_versioned_writer(service: UserService):
    user = local_user(version=7)
    updated = local_user(version=8, password="admin-reset-hash")
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = updated
    service.auth_service.verify_password.return_value = False
    service.auth_service.create_salt_and_hashed_password.return_value = (
        "admin-reset-salt",
        "admin-reset-hash",
    )

    result = await service.update_user(
        user.id, UserUpdatePublic(password=VALID_PASSWORD)
    )

    assert result == updated
    update = service.repo.update.await_args.args[0]
    assert update.password == "admin-reset-hash"
    assert update.credential_version == 8


async def test_invalidate_sessions_only_advances_credential_version(
    service: UserService,
):
    user = local_user(version=2)
    updated = local_user(version=3)
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = updated

    result = await service.invalidate_sessions(user_id=user.id)

    assert result == updated
    update = service.repo.update.await_args.args[0]
    assert update.credential_version == 3
    assert update.password is None
    assert "password" not in update.model_fields_set


async def test_password_lock_forces_fresh_state_from_the_database():
    repository = object.__new__(UsersRepository)
    load = AsyncMock(return_value=local_user())
    repository._get_model_from_query = load

    await repository.get_user_by_id_for_update(TEST_USER.id)

    query = load.await_args.args[0]
    assert query.get_execution_options()["populate_existing"] is True
    compiled = str(query.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


async def test_token_lookup_preserves_raw_claim_presence(service: UserService):
    user = local_user(version=3)
    provider_claims = {"iss": "https://identity.example.test"}
    service.auth_service.get_jwt_payload_with_claims.return_value = (
        SimpleNamespace(username=user.username),
        provider_claims,
    )
    service.repo.get_user_by_username.return_value = user

    assert await service._get_user_from_token("verified-token") == user

    service.auth_service.validate_credential_version.assert_called_once_with(
        provider_claims, user
    )


def test_password_failures_have_stable_error_codes_and_statuses():
    assert DOMAIN_EXCEPTION_MAP[CurrentPasswordIncorrectError] == (
        400,
        None,
        ErrorCodes.CURRENT_PASSWORD_INCORRECT,
    )
    assert DOMAIN_EXCEPTION_MAP[PasswordReuseError][2] == ErrorCodes.PASSWORD_REUSE
    assert (
        DOMAIN_EXCEPTION_MAP[PasswordPolicyViolationError][2]
        == ErrorCodes.PASSWORD_POLICY_VIOLATION
    )
    assert DOMAIN_EXCEPTION_MAP[LocalPasswordChangeUnavailableError] == (
        409,
        None,
        ErrorCodes.LOCAL_PASSWORD_CHANGE_UNAVAILABLE,
    )


async def test_current_user_capability_is_explicit_for_each_password_owner():
    api_key_repo = AsyncMock()
    api_key_repo.get_latest_active_by_owner.return_value = None
    container = SimpleNamespace(api_key_v2_repo=lambda: api_key_repo)

    local = await user_router.get_currently_authenticated_user(
        current_user=local_user(), container=container
    )
    external = await user_router.get_currently_authenticated_user(
        current_user=local_user(password=None), container=container
    )

    assert local.password_change.source == "eneo"
    assert local.password_change.policy.min_length == 15
    assert local.password_change.policy.max_bytes == 72
    assert external.password_change.source == "external"
    assert external.password_change.policy is None


async def test_password_route_audits_only_static_metadata(monkeypatch):
    user = local_user()
    updated = local_user(version=1, password="new-hash")
    service = AsyncMock()
    service.change_local_password.return_value = updated
    audit = AsyncMock()
    container = SimpleNamespace(
        user=lambda: user,
        user_service=lambda: service,
        audit_service=lambda: audit,
        redis_client=lambda: AsyncMock(),
    )
    rate_limit = AsyncMock()
    monkeypatch.setattr(user_router, "enforce_rate_limit", rate_limit)

    response = await user_router.change_current_user_password(
        password_change=PasswordChangeRequest(
            current_password="current secret value",
            new_password=VALID_PASSWORD,
        ),
        container=container,
        _session_guard=None,
    )

    assert response.status_code == 204
    rate_limit.assert_awaited_once()
    audit_call = audit.log_async.await_args.kwargs
    assert audit_call["action"] == ActionType.PASSWORD_CHANGED
    rendered_audit = repr(audit_call)
    assert "current secret value" not in rendered_audit
    assert VALID_PASSWORD not in rendered_audit


async def test_password_route_rate_limits_before_password_verification(monkeypatch):
    user = local_user()
    service = AsyncMock()
    audit = AsyncMock()
    container = SimpleNamespace(
        user=lambda: user,
        user_service=lambda: service,
        audit_service=lambda: audit,
        redis_client=lambda: AsyncMock(),
    )
    result = RateLimitResult(
        allowed=False,
        current_count=6,
        max_requests=5,
        window_seconds=15 * 60,
    )
    monkeypatch.setattr(
        user_router,
        "enforce_rate_limit",
        AsyncMock(side_effect=RateLimitExceededError(result)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await user_router.change_current_user_password(
            password_change=PasswordChangeRequest(
                current_password="current secret value",
                new_password=VALID_PASSWORD,
            ),
            container=container,
            _session_guard=None,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "rate_limit_exceeded"
    assert exc_info.value.headers == {"Retry-After": "900"}
    service.change_local_password.assert_not_awaited()
    assert (
        audit.log_async.await_args.kwargs["action"] == ActionType.PASSWORD_CHANGE_FAILED
    )


async def test_password_route_fails_closed_when_rate_limiter_is_unavailable(
    monkeypatch,
):
    user = local_user()
    service = AsyncMock()
    audit = AsyncMock()
    container = SimpleNamespace(
        user=lambda: user,
        user_service=lambda: service,
        audit_service=lambda: audit,
        redis_client=lambda: AsyncMock(),
    )
    monkeypatch.setattr(
        user_router,
        "enforce_rate_limit",
        AsyncMock(
            side_effect=RateLimitServiceUnavailableError(
                RuntimeError("redis unavailable")
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await user_router.change_current_user_password(
            password_change=PasswordChangeRequest(
                current_password="current secret value",
                new_password=VALID_PASSWORD,
            ),
            container=container,
            _session_guard=None,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "rate_limit_unavailable"
    service.change_local_password.assert_not_awaited()
    audit.log_async.assert_not_awaited()


def test_password_mutation_routes_require_session_auth():
    endpoints = {
        user_router.change_current_user_password,
        user_router.invalidate_current_user_sessions,
    }
    matching_routes = [
        route for route in user_router.router.routes if route.endpoint in endpoints
    ]
    assert len(matching_routes) == 2
    for route in matching_routes:
        dependency_calls = {
            dependency.call for dependency in route.dependant.dependencies
        }
        assert require_session_auth in dependency_calls


def test_credential_version_enforcement_respects_token_issuer():
    service = AuthService()
    user = local_user(version=2)

    service.validate_credential_version(
        {"iss": JWT_ISSUER, "credential_version": 2}, user
    )
    with pytest.raises(AuthenticationException):
        service.validate_credential_version(
            {"iss": JWT_ISSUER, "credential_version": 1},
            user,
        )

    legacy_user = local_user(version=0)
    service.validate_credential_version({"iss": JWT_ISSUER}, legacy_user)
    with pytest.raises(AuthenticationException):
        service.validate_credential_version({"iss": JWT_ISSUER}, user)

    # Provider-owned sessions without Eneo's claim remain usable after the
    # Eneo counter advances; otherwise every future Zitadel login locks out.
    service.validate_credential_version({"iss": "https://identity.example.test"}, user)


@pytest.mark.parametrize("invalid_version", [True, "2", None, 2.0])
def test_present_credential_version_claim_requires_a_strict_integer(invalid_version):
    with pytest.raises(AuthenticationException):
        AuthService.validate_credential_version(
            {
                "iss": "https://identity.example.test",
                "credential_version": invalid_version,
            },
            local_user(version=2),
        )


def test_historical_overlong_bcrypt_passwords_still_verify_but_cannot_be_written():
    historical_hash = bcrypt.hashpw(b"a" * 72, bcrypt.gensalt()).decode("utf-8")

    assert AuthService.verify_password("a" * 80, historical_hash)
    with pytest.raises(ValueError, match="maximum input size"):
        AuthService().create_salt_and_hashed_password("a" * 73)
