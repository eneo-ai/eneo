from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.authentication.auth_models import AccessToken, ApiKeyCreated
from intric.main.exceptions import AuthenticationException, UniqueUserException
from intric.settings.settings import SettingsUpsert
from intric.main.models import ModelId
from intric.users.user import (
    PropUserInvite,
    UserAdd,
    UserAddSuperAdmin,
    UserInDB,
    UserState,
    UserUpdate,
)
from intric.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER


@pytest.fixture(name="service")
def service_with_mocks():
    return UserService(
        user_repo=AsyncMock(),
        auth_service=AsyncMock(),
        api_key_auth_resolver=AsyncMock(),
        api_key_v2_repo=AsyncMock(),
        allowed_origin_repo=AsyncMock(),
        audit_service=AsyncMock(),
        settings_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        info_blob_repo=AsyncMock(),
    )


async def test_login_user_fails_with_no_user_with_that_email(service: UserService):
    service.repo.get_user_by_email.return_value = None

    with pytest.raises(AuthenticationException, match="Invalid credentials"):
        await service.login(email="hacker@notindatabase.com", password="password?")


async def test_login_user_fails_if_hashed_passwords_do_not_match(service: UserService):
    service.auth_service.verify_password = MagicMock()
    service.auth_service.verify_password.return_value = False

    with pytest.raises(AuthenticationException, match="Invalid credentials"):
        await service.login(
            email="realuser@indatabase.com", password="iamhackeristhisthepassword?"
        )


async def test_login_successful_returns_access_token(service: UserService):
    service.auth_service.verify_password = MagicMock()
    service.auth_service.verify_password.return_value = True
    service.auth_service.create_access_token_for_user = MagicMock()
    service.auth_service.create_access_token_for_user.return_value = (
        "bingobongo you have access"
    )

    access_token = await service.login(email="realuser@indatabase.com", password="1234")

    assert access_token == AccessToken(
        access_token="bingobongo you have access", token_type="bearer"
    )


async def test_register_user_fails_if_email_is_taken(service: UserService):
    service.repo.get_user_by_email.return_value = TEST_USER
    new_user = UserAddSuperAdmin(
        email=TEST_USER.email,
        username="realuser",
        password="1234sdf",
        tenant_id=TEST_TENANT.id,
    )

    with pytest.raises(
        UniqueUserException,
        match="That email is already taken.",
    ):
        await service.register(new_user)


async def test_register_user_fails_if_username_is_taken(service: UserService):
    service.repo.get_user_by_email.return_value = None
    new_user = UserAddSuperAdmin(
        email="realuser@test.com",
        username=TEST_USER.username,
        password="1234asd",
        tenant_id=TEST_TENANT.id,
    )

    with pytest.raises(
        UniqueUserException,
        match="That username is already taken.",
    ):
        await service.register(new_user)


async def test_register_user_creates_a_user_and_settings(service: UserService):
    service.repo.get_user_by_email.return_value = None
    service.repo.get_user_by_username.return_value = None
    service.tenant_repo.get.return_value = TEST_TENANT
    test_salt = "test_salt"
    hashed_password = "hashed_password"

    expected_user_upsert = UserAdd(
        email="realuser@test.com",
        username="realuser",
        password=hashed_password,
        salt=test_salt,
        tenant_id=TEST_TENANT.id,
        quota_used=0,
        quota_limit=None,
        state="active",
    )
    expected_user_in_db = UserInDB(
        **expected_user_upsert.model_dump(
            exclude_none=True, exclude={"predefined_roles"}
        ),
        id=uuid4(),
        tenant=TEST_TENANT,
        predefined_roles=[],
    )

    expected_settings = SettingsUpsert(
        user_id=expected_user_in_db.id,
    )

    service.repo.add.return_value = expected_user_in_db
    service.auth_service.create_salt_and_hashed_password = MagicMock()
    service.auth_service.create_salt_and_hashed_password.return_value = (
        test_salt,
        hashed_password,
    )
    service.auth_service._create_and_hash_api_key.return_value = ApiKeyCreated(
        key="api_key", truncated_key="ey", hashed_key="4p1 k3y"
    )
    service.auth_service.create_access_token_for_user = MagicMock()
    service.auth_service.create_access_token_for_user.return_value = (
        "bingobongo you have access"
    )
    service.repo.add.return_value = expected_user_in_db

    new_user = UserAddSuperAdmin(
        email="realuser@test.com",
        username="realuser",
        password="1234asd",
        tenant_id=TEST_TENANT.id,
    )

    user, access_token, api_key = await service.register(new_user)

    assert user == expected_user_in_db

    service.repo.add.assert_awaited_with(expected_user_upsert)
    service.settings_repo.add.assert_awaited_with(expected_settings)


async def test_update_used_tokens(service: UserService):
    user = UserInDB(**TEST_USER.model_dump(exclude_none=True))
    user.used_tokens = 13
    service.repo.get_user_by_id.return_value = user

    tokens_to_add = 47
    expected_upsert = UserUpdate(
        id=user.id, used_tokens=user.used_tokens + tokens_to_add
    )

    await service.update_used_tokens(TEST_USER.id, 47)

    service.repo.update.assert_awaited_with(expected_upsert)


async def test_invite_user_creates_user_and_settings(service: UserService):
    service.repo.get_user_by_email.return_value = None
    service.repo.get_user_by_username.return_value = None
    service.tenant_repo.get.return_value = TEST_TENANT

    role_id = uuid4()
    user_invite = PropUserInvite(
        email="invitee@test.com", predefined_role=ModelId(id=role_id)
    )

    expected_user_upsert = UserAdd(
        email="invitee@test.com",
        tenant_id=TEST_TENANT.id,
        state=UserState.INVITED,
        predefined_roles=[ModelId(id=role_id)],
    )
    expected_user_in_db = UserInDB(
        **expected_user_upsert.model_dump(
            exclude_none=True, exclude={"predefined_roles"}
        ),
        id=uuid4(),
        tenant=TEST_TENANT,
        predefined_roles=[],
    )

    service.repo.add.return_value = expected_user_in_db

    user = await service.invite_user(user_invite, tenant_id=TEST_TENANT.id)

    assert user == expected_user_in_db
    service.repo.add.assert_awaited_with(expected_user_upsert)
    service.settings_repo.add.assert_awaited_with(
        SettingsUpsert(user_id=expected_user_in_db.id)
    )


async def test_authenticate_fails_if_no_token_and_no_api_key(service: UserService):
    with pytest.raises(AuthenticationException, match="No authenticated user."):
        await service.authenticate(None, None)
