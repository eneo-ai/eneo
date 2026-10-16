"""Local password lifecycle: one-time admin-set passwords and rotation."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from eneo.authentication.auth_models import JWTPayload
from eneo.authentication.auth_service import AuthService
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    access_for,
    authorize_user,
    endpoint_access,
)
from eneo.main.exceptions import ErrorCodes
from eneo.server.exception_handlers import DOMAIN_EXCEPTION_MAP
from eneo.users import user_router
from eneo.users.password import (
    PasswordChangeRequiredError,
    PasswordLifecyclePolicy,
    PasswordLifecyclePolicyUpdate,
    evaluate_password_status,
)
from eneo.users.user import UserAddSuperAdmin, UserUpdatePublic
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
VALID_PASSWORD = "correct horse battery staple"
UNIT_SECRET = "unit-test-secret-with-at-least-thirty-two-bytes"


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


def tenant_with_policy(**policy):
    return TEST_TENANT.model_copy(update={"password_policy": policy})


def password_user(
    *,
    change_required: bool = False,
    changed_at: datetime | None = NOW,
    session_auth_method: str | None = "password",
    password: str | None = "local-hash",
    **policy,
):
    return TEST_USER.model_copy(
        update={
            "password": password,
            "password_change_required": change_required,
            "password_changed_at": changed_at,
            "session_auth_method": session_auth_method,
            "tenant": tenant_with_policy(**policy),
        }
    )


# --- Policy model -----------------------------------------------------------


def test_policy_defaults_apply_to_rows_written_before_a_key_existed():
    assert PasswordLifecyclePolicy.from_tenant(None) == PasswordLifecyclePolicy(
        require_change_after_admin_set=True, max_age_days=None
    )
    partial = PasswordLifecyclePolicy.from_tenant({"max_age_days": 90})
    assert partial.require_change_after_admin_set is True
    assert partial.max_age_days == 90


def test_policy_ignores_unknown_stored_keys_but_updates_forbid_them():
    assert PasswordLifecyclePolicy.from_tenant({"later_key": 1}).max_age_days is None
    with pytest.raises(ValidationError):
        PasswordLifecyclePolicyUpdate.model_validate({"later_key": 1})


@pytest.mark.parametrize("days", [0, -1, 3651])
def test_max_age_must_be_between_one_day_and_ten_years(days):
    with pytest.raises(ValidationError):
        PasswordLifecyclePolicyUpdate(max_age_days=days)


# --- Status evaluation ------------------------------------------------------


def test_admin_set_password_requires_change_regardless_of_age():
    status = evaluate_password_status(
        change_required=True,
        changed_at=NOW,
        policy=PasswordLifecyclePolicy(max_age_days=90),
        now=NOW,
    )
    assert status.change_required is True
    assert status.reason == "admin_set"
    assert status.expires_at == NOW + timedelta(days=90)


def test_password_expires_exactly_at_max_age():
    policy = PasswordLifecyclePolicy(max_age_days=30)
    changed_at = NOW - timedelta(days=30)
    expired = evaluate_password_status(
        change_required=False, changed_at=changed_at, policy=policy, now=NOW
    )
    assert expired.change_required is True
    assert expired.reason == "expired"
    assert expired.expires_at == NOW

    fresh = evaluate_password_status(
        change_required=False,
        changed_at=changed_at + timedelta(seconds=1),
        policy=policy,
        now=NOW,
    )
    assert fresh.change_required is False
    assert fresh.reason is None


def test_without_max_age_or_change_time_nothing_expires():
    no_rotation = evaluate_password_status(
        change_required=False,
        changed_at=NOW - timedelta(days=5000),
        policy=PasswordLifecyclePolicy(),
        now=NOW,
    )
    assert no_rotation.change_required is False
    assert no_rotation.expires_at is None

    unknown_age = evaluate_password_status(
        change_required=False,
        changed_at=None,
        policy=PasswordLifecyclePolicy(max_age_days=1),
        now=NOW,
    )
    assert unknown_age.change_required is False
    assert unknown_age.expires_at is None


# --- Credential writes ------------------------------------------------------


async def test_self_service_change_clears_the_requirement(service: UserService):
    user = password_user(change_required=True)
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = user
    service.auth_service.verify_password.side_effect = [True, False]
    service.auth_service.create_salt_and_hashed_password.return_value = (
        "salt",
        "hashed-value",
    )

    await service.change_local_password(
        user_id=user.id, current_password="one-time", new_password=VALID_PASSWORD
    )

    update = service.repo.update.await_args.args[0]
    assert update.password_change_required is False
    assert update.password_changed_at is not None
    assert update.password_changed_at.tzinfo is not None


@pytest.mark.parametrize(
    "require_after_admin_set, expected", [(True, True), (False, False)]
)
async def test_admin_reset_follows_the_tenant_policy(
    service: UserService, require_after_admin_set, expected
):
    user = password_user(require_change_after_admin_set=require_after_admin_set)
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = user
    service.auth_service.verify_password.return_value = False
    service.auth_service.create_salt_and_hashed_password.return_value = (
        "salt",
        "hashed-value",
    )

    await service.update_user(user.id, UserUpdatePublic(password=VALID_PASSWORD))

    update = service.repo.update.await_args.args[0]
    assert update.password_change_required is expected
    assert update.password_changed_at is not None


async def test_session_invalidation_leaves_the_lifecycle_alone(service: UserService):
    user = password_user(change_required=True)
    service.repo.get_user_by_id_for_update.return_value = user
    service.repo.update.return_value = user

    await service.invalidate_sessions(user_id=user.id)

    update = service.repo.update.await_args.args[0]
    assert "password_change_required" not in update.model_fields_set
    assert "password_changed_at" not in update.model_fields_set


@pytest.mark.parametrize(
    "override, policy_requires, expected",
    [
        (None, True, True),
        (None, False, False),
        (False, True, False),
        (True, False, True),
    ],
)
async def test_registration_with_a_password_stamps_the_lifecycle(
    service: UserService, override, policy_requires, expected
):
    service.repo.get_user_by_email.return_value = None
    service.repo.get_user_by_username.return_value = None
    service.tenant_repo.get.return_value = tenant_with_policy(
        require_change_after_admin_set=policy_requires
    )
    service.repo.add.return_value = password_user()
    service.auth_service.create_salt_and_hashed_password.return_value = (
        "salt",
        "hashed-value",
    )
    service.auth_service.create_access_token_for_user.return_value = "token"

    await service.register(
        UserAddSuperAdmin(
            email="new@example.com",
            username="new",
            password=VALID_PASSWORD,
            tenant_id=TEST_TENANT.id,
            password_change_required=override,
        )
    )

    added = service.repo.add.await_args.args[0]
    assert added.password_change_required is expected
    assert added.password_changed_at is not None


async def test_registration_without_a_password_has_no_lifecycle(service: UserService):
    service.repo.get_user_by_email.return_value = None
    service.repo.get_user_by_username.return_value = None
    service.tenant_repo.get.return_value = TEST_TENANT
    service.repo.add.return_value = password_user(password=None)
    service.auth_service.create_access_token_for_user.return_value = "token"

    await service.register(
        UserAddSuperAdmin(
            email="sso@example.com", username="sso", tenant_id=TEST_TENANT.id
        )
    )

    added = service.repo.add.await_args.args[0]
    assert added.password_change_required is False
    assert added.password_changed_at is None


# --- Session claim ----------------------------------------------------------


def test_only_the_password_login_marks_its_session(monkeypatch):
    monkeypatch.setattr("eneo.authentication.auth_service.JWT_SECRET", UNIT_SECRET)
    auth = AuthService()
    user = password_user()

    password_token = auth.create_access_token_for_user(
        user, secret_key=UNIT_SECRET, auth_method="password"
    )
    other_token = auth.create_access_token_for_user(user, secret_key=UNIT_SECRET)

    password_claims = auth.get_jwt_payload(password_token, key=UNIT_SECRET)
    other_claims = auth.get_jwt_payload(other_token, key=UNIT_SECRET)
    assert password_claims.auth_method == "password"
    assert other_claims.auth_method is None


async def test_password_login_mints_a_password_session(service: UserService):
    user = password_user()
    service.repo.get_user_by_email.return_value = user
    service.auth_service.verify_password.return_value = True
    service.auth_service.create_access_token_for_user.return_value = "token"
    service.tenant_repo.get.return_value = user.tenant

    await service.login(email=user.email, password="whatever")

    kwargs = service.auth_service.create_access_token_for_user.call_args.kwargs
    assert kwargs["auth_method"] == "password"


async def test_token_resolution_records_the_session_auth_method(service: UserService):
    user = password_user(session_auth_method=None)
    service.repo.get_user_by_id_and_tenant_id.return_value = user
    payload = JWTPayload(
        iss="eneo",
        aud="eneo",
        iat=1.0,
        exp=2.0,
        token_version=2,
        user_id=user.id,
        tenant_id=user.tenant_id,
        credential_version=user.credential_version,
        auth_method="password",
        sub=user.email,
    )

    resolved = await service._get_user_from_payload(payload)

    assert resolved is not None
    assert resolved.session_auth_method == "password"
    assert "session_auth_method" not in resolved.model_dump()


# --- Access gate ------------------------------------------------------------


def gated_endpoint(*, allowed: bool = False):
    @endpoint_access(
        authentication=Authentication.USER,
        authorization=Authorization.AUTHENTICATED,
        reason="Unit test",
        allowed_pending_password_change=allowed,
    )
    async def endpoint() -> None: ...

    return endpoint


def connection_for(endpoint):
    return SimpleNamespace(scope={"endpoint": endpoint})


def test_password_session_with_admin_set_password_is_blocked():
    user = password_user(change_required=True)
    with pytest.raises(PasswordChangeRequiredError) as blocked:
        authorize_user(connection_for(gated_endpoint()), user)
    assert blocked.value.details == {"reason": "admin_set"}


def test_password_session_with_expired_password_is_blocked():
    user = password_user(changed_at=NOW - timedelta(days=400), max_age_days=365)
    with pytest.raises(PasswordChangeRequiredError) as blocked:
        authorize_user(connection_for(gated_endpoint()), user)
    assert blocked.value.details == {"reason": "expired"}


def test_the_password_change_endpoints_stay_reachable():
    user = password_user(change_required=True)
    authorize_user(connection_for(gated_endpoint(allowed=True)), user)


@pytest.mark.parametrize("session_auth_method", [None])
def test_federated_sessions_ignore_the_local_password_lifecycle(session_auth_method):
    user = password_user(
        change_required=True,
        changed_at=NOW - timedelta(days=400),
        session_auth_method=session_auth_method,
        max_age_days=30,
    )
    authorize_user(connection_for(gated_endpoint()), user)


def test_compliant_password_sessions_pass():
    user = password_user(changed_at=NOW - timedelta(days=10), max_age_days=30)
    authorize_user(connection_for(gated_endpoint()), user)


def test_only_the_password_change_routes_are_exempt_from_the_gate():
    exempt = {
        route.path
        for route in user_router.router.routes
        if (policy := access_for(getattr(route, "endpoint", None))) is not None
        and policy.allowed_pending_password_change
    }
    assert exempt == {
        "/me/",
        "/me/password/",
        "/me/sessions/invalidate/",
        "/password-policy/",
    }


def test_blocked_sessions_get_a_stable_forbidden_code():
    assert DOMAIN_EXCEPTION_MAP[PasswordChangeRequiredError] == (
        403,
        None,
        ErrorCodes.PASSWORD_CHANGE_REQUIRED,
    )


# --- Current user -----------------------------------------------------------


async def test_current_user_reports_the_password_status():
    api_key_repo = AsyncMock()
    api_key_repo.get_latest_active_by_owner.return_value = None
    container = SimpleNamespace(api_key_v2_repo=lambda: api_key_repo)

    pending = await user_router.get_currently_authenticated_user(
        current_user=password_user(change_required=True, max_age_days=90),
        container=container,
    )
    assert pending.password_status is not None
    assert pending.password_status.change_required is True
    assert pending.password_status.reason == "admin_set"
    assert pending.password_status.expires_at == NOW + timedelta(days=90)

    external = await user_router.get_currently_authenticated_user(
        current_user=password_user(password=None), container=container
    )
    assert external.password_status is None
