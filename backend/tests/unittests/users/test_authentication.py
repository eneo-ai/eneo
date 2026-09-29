from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt
import pytest
from pydantic import ValidationError

from eneo.authentication import auth_service as auth_service_module
from eneo.authentication.auth_service import AuthService
from eneo.internal_mcp.foundation import (
    assistant_id_from_token,
    mcp_server_id_from_token,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    AuthenticationException,
    TenantSuspendedException,
    UserInactiveException,
)
from eneo.tenants.tenant import TenantState
from eneo.users.user import UserInDB, UserState
from eneo.users.user_repo import UsersRepository
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT_2, TEST_USER

JWT_ALGORITHM = get_settings().jwt_algorithm
JWT_AUDIENCE = get_settings().jwt_audience
JWT_EXPIRY_TIME_MINUTES = get_settings().jwt_expiry_time
JWT_SECRET = "unit-test-secret-padded-to-the-hs256-minimum"


@pytest.fixture
def auth_service(monkeypatch):
    monkeypatch.setattr(auth_service_module, "JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr(get_settings(), "jwt_secret", JWT_SECRET)
    return AuthService()


async def test_can_create_access_token_successfully(auth_service: AuthService):
    access_token = auth_service.create_access_token_for_user(
        user=TEST_USER,
        secret_key=str(JWT_SECRET),
        audience=JWT_AUDIENCE,
        expires_in=JWT_EXPIRY_TIME_MINUTES,
    )
    creds = jwt.decode(
        access_token,
        str(JWT_SECRET),
        audience=JWT_AUDIENCE,
        algorithms=[JWT_ALGORITHM],
    )
    assert creds.get("username") is not None
    assert creds["username"] == TEST_USER.username
    assert creds["aud"] == JWT_AUDIENCE
    assert creds["user_id"] == str(TEST_USER.id)
    assert creds["tenant_id"] == str(TEST_USER.tenant_id)
    assert creds["token_version"] == 2


async def test_token_missing_user_is_invalid(auth_service: AuthService):
    with pytest.raises(ValueError, match="user is required"):
        auth_service.create_access_token_for_user(
            user=None,
            secret_key=str(JWT_SECRET),
            audience=JWT_AUDIENCE,
            expires_in=JWT_EXPIRY_TIME_MINUTES,
        )


@pytest.mark.parametrize(
    "secret_key, jwt_audience, exception",
    (
        (
            "wrong-secret-padded-to-the-hs256-minimum-length",
            JWT_AUDIENCE,
            jwt.InvalidSignatureError,
        ),
        (
            "another-wrong-secret-of-sufficient-key-length",
            JWT_AUDIENCE,
            jwt.InvalidSignatureError,
        ),
        (JWT_SECRET, "othersite:auth", jwt.InvalidAudienceError),
        (JWT_SECRET, None, ValidationError),
    ),
)
async def test_invalid_token_content_raises_error(
    auth_service: AuthService, secret_key, jwt_audience, exception
):
    with pytest.raises(exception):
        access_token = auth_service.create_access_token_for_user(
            user=TEST_USER,
            secret_key=str(secret_key),
            audience=jwt_audience,
            expires_in=JWT_EXPIRY_TIME_MINUTES,
        )
        jwt.decode(
            access_token,
            str(JWT_SECRET),
            audience=JWT_AUDIENCE,
            algorithms=[JWT_ALGORITHM],
        )


@pytest.mark.parametrize(
    "secret, wrong_token",
    (
        (JWT_SECRET, "asdf"),  # use wrong token
        (JWT_SECRET, ""),  # use wrong token
        (JWT_SECRET, None),  # use wrong token
        (
            "wrong-decode-secret-of-sufficient-key-length",
            "use correct token",
        ),  # use wrong secret
    ),
)
async def test_error_when_token_or_secret_is_wrong(
    auth_service: AuthService, secret, wrong_token
) -> None:
    token = auth_service.create_access_token_for_user(
        user=TEST_USER, secret_key=str(JWT_SECRET)
    )
    if wrong_token == "use correct token":
        wrong_token = token
    with pytest.raises(
        AuthenticationException, match="Could not validate token credentials."
    ):
        auth_service.get_jwt_payload_with_claims(
            token=wrong_token,
            key=str(secret),
        )


def test_validate_openid_jwt(auth_service: AuthService):
    access_token = "lApcsgZoeiZqM1pLUcVauAY9T3jtPEm45AN3h7Z3cKk"
    id_token = (
        "eyJraWQiOiJpS2phIiwiYWxnIjoiUlMyNTYifQ.eyJhdF9oYXNoIjoi"
        "T2wxck1oeGQ5TWZuYzd2RVVmOGdwdyIsInN1YiI6Inhqb25jZXIiLCJ"
        "hdWQiOiJpbnRyaWMiLCJhenAiOiJpbnRyaWMiLCJhdXRoX3RpbWUiOj"
        "E3MDM1OTI5ODUsImlzcyI6Imh0dHBzOi8vbTAwLW1nLWxvY2FsLmxvZ"
        "2ludGVzdC5zdW5kc3ZhbGwuc2UvbWctbG9jYWwvaW50cmljIiwiZXhw"
        "IjoxNzAzNTkzOTAzLCJpYXQiOjE3MDM1OTMwMDMsIm5vbmNlIjoidGV"
        "zdF9ub25jZSJ9.cWeXjP7oHswOo-HJ98C4YsEk3otnEZZJB_KJ8rwyi"
        "MUb5geHSmDb0g0IQkFLj1P5109WF7bzpJPUekUcZ1LFtvrXmv48uAmG"
        "ZARm4PQkcgm-vrtHuiT20-vh3vj9e5Y32eiKocKwgkppMXyBFpIxBeV"
        "yLIyGYfzM9YgKh5ekVymUFexxtAjEd1r2sQQuajcbS-zjbMU2RDVXNA"
        "dW1mfgy79WhDlUQAaQAQKi0DFdCb64wEtAJl-EoQn-PIAYIBeoJnG6S"
        "2kjtVKVICiX9NMNgHS2CwOXScKWDLCBxzyPWNIW905APBJBJiTL-HxV"
        "AyUXjne3PAQWq-hk8_gLMV6HIw"
    )

    key = jwt.PyJWK(
        {
            "kty": "RSA",
            "e": "AQAB",
            "use": "sig",
            "kid": "iKja",
            "n": (
                "1qJunykEdXnNfYN5Ihs7affK0gGldIxJmCelDDh1FyHPBkRIwI2"
                "B074z5RP0qXGLh-9MaFerAXiuX1icszYN85Pxt2zqeaKGWWnQAl"
                "5QmUR03D71MO2FwN6Vb3C1ytg-k73PYK3TKyDjC0i0bRHB7gh7t"
                "zMKTZqkRmfkEXjw25iCuWRMtKTaeQnqcXc9x4Hu8E37mW6csfN7"
                "FvB8jFglA2dAFw1Hvv3f6qd4nJGfJ99NoI0woMuh44lmwj2MqUF"
                "V24WkzvBebCL-IEtSwBcf6qk3e0U92BBDbhfnSK2lPSP9NHFj-c"
                "xeBa27bNlLFQXK_DjXTvufYhdNI29Q7emGZw"
            ),
        }
    )
    signing_algos = ["RS256"]

    payload = auth_service.get_payload_from_openid_jwt(
        id_token=id_token,
        access_token=access_token,
        key=key.key,
        signing_algos=signing_algos,
        client_id="intric",  # matches the aud claim in the hardcoded JWT above
        options={"verify_exp": False},
    )

    assert payload["sub"] == "xjoncer"


@pytest.fixture
def session_service(auth_service: AuthService):
    users: dict[UUID, UserInDB] = {}

    async def find_user(user_id: UUID, tenant_id: UUID) -> UserInDB | None:
        user = users.get(user_id)
        if user is None or user.tenant_id != tenant_id or user.deleted_at is not None:
            return None
        return user

    repo = AsyncMock(spec=UsersRepository)
    repo.get_user_by_id_and_tenant_id.side_effect = find_user
    # A fallback to mutable names is a regression even if a token later fails.
    repo.get_user_by_username.side_effect = AssertionError("username authentication")
    repo.get_user_by_email.side_effect = AssertionError("email authentication")
    service = UserService(
        user_repo=repo,
        auth_service=auth_service,
        api_key_auth_resolver=AsyncMock(),
        api_key_v2_repo=AsyncMock(),
        audit_service=AsyncMock(),
        settings_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        info_blob_repo=AsyncMock(),
    )
    return service, users


def token_claims(token: str) -> dict[str, object]:
    settings = get_settings()
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
    )


def sign_claims(claims: dict[str, object]) -> str:
    return jwt.encode(claims, JWT_SECRET, algorithm=get_settings().jwt_algorithm)


@pytest.mark.parametrize("same_tenant", [False, True])
@pytest.mark.parametrize("scoped_mcp", [False, True])
async def test_same_username_sessions_keep_their_own_identity(
    session_service, same_tenant: bool, scoped_mcp: bool
):
    service, users = session_service
    tenant = TEST_USER.tenant if same_tenant else TEST_TENANT_2
    anna = TEST_USER.model_copy(
        update={"username": "anna.svensson", "email": "anna.svensson@sundsvall.se"}
    )
    other_anna = anna.model_copy(
        update={
            "id": uuid4(),
            "email": "anna.svensson@ange.se",
            "tenant_id": tenant.id,
            "tenant": tenant,
        }
    )
    users.update({anna.id: anna, other_anna.id: other_anna})

    for owner in (anna, other_anna):
        token = (
            service.auth_service.create_scoped_mcp_token(owner, assistant_id=uuid4())
            if scoped_mcp
            else service.auth_service.create_access_token_for_user(owner)
        )
        actual = await service.authenticate(token=token)
        assert (actual.id, actual.tenant_id, actual.email) == (
            owner.id,
            owner.tenant_id,
            owner.email,
        )


async def test_session_does_not_need_a_username(session_service):
    service, users = session_service
    user = TEST_USER.model_copy(update={"username": None})
    users[user.id] = user
    token = service.auth_service.create_access_token_for_user(user)
    assert (await service.authenticate(token=token)).id == user.id


async def test_name_and_email_changes_do_not_transfer_a_session(session_service):
    service, users = session_service
    token = service.auth_service.create_access_token_for_user(TEST_USER)
    renamed = TEST_USER.model_copy(
        update={"username": "new-name", "email": "new@example.com"}
    )
    replacement = TEST_USER.model_copy(update={"id": uuid4()})
    users.update({renamed.id: renamed, replacement.id: replacement})
    assert (await service.authenticate(token=token)).id == renamed.id

    users[renamed.id] = renamed.model_copy(
        update={"deleted_at": datetime.now(timezone.utc)}
    )
    with pytest.raises(AuthenticationException):
        await service.authenticate(token=token)


@pytest.mark.parametrize("change", ["tenant", "deleted", "credentials", "missing"])
async def test_session_rejects_changed_or_missing_identity(
    session_service, change: str
):
    service, users = session_service
    token = service.auth_service.create_access_token_for_user(TEST_USER)
    if change == "tenant":
        users[TEST_USER.id] = TEST_USER.model_copy(
            update={"tenant_id": TEST_TENANT_2.id, "tenant": TEST_TENANT_2}
        )
    elif change == "deleted":
        users[TEST_USER.id] = TEST_USER.model_copy(
            update={"deleted_at": datetime.now(timezone.utc)}
        )
    elif change == "credentials":
        users[TEST_USER.id] = TEST_USER.model_copy(
            update={"credential_version": TEST_USER.credential_version + 1}
        )
    with pytest.raises(AuthenticationException):
        await service.authenticate(token=token)


@pytest.mark.parametrize(
    "claim",
    [
        "user_id",
        "tenant_id",
        "credential_version",
        "token_version",
        "sub",
        "iss",
        "aud",
        "iat",
        "exp",
    ],
)
async def test_session_rejects_missing_required_claim(session_service, claim: str):
    service, users = session_service
    users[TEST_USER.id] = TEST_USER
    claims = token_claims(service.auth_service.create_access_token_for_user(TEST_USER))
    del claims[claim]
    with pytest.raises(AuthenticationException):
        await service.authenticate(token=sign_claims(claims))


@pytest.mark.parametrize(
    "claim,value",
    [
        ("user_id", "not-a-uuid"),
        ("user_id", "00000000-0000-4000-8000-000000000001"),
        ("tenant_id", "not-a-uuid"),
        ("tenant_id", "00000000-0000-4000-8000-000000000002"),
        ("token_version", 1),
        ("token_version", 3),
        ("token_version", "2"),
        ("credential_version", "0"),
        ("credential_version", True),
        ("credential_version", -1),
        ("iss", "https://identity.example.com"),
        ("aud", "another-application"),
        ("exp", 1),
    ],
)
async def test_session_rejects_invalid_signed_claims(
    session_service, claim: str, value: object
):
    service, users = session_service
    users[TEST_USER.id] = TEST_USER
    claims = token_claims(service.auth_service.create_access_token_for_user(TEST_USER))
    claims[claim] = value
    with pytest.raises(AuthenticationException):
        await service.authenticate(token=sign_claims(claims))


async def test_legacy_session_is_rejected_even_when_its_username_is_unique(
    session_service,
):
    service, users = session_service
    users[TEST_USER.id] = TEST_USER
    claims = token_claims(service.auth_service.create_access_token_for_user(TEST_USER))
    for field in ("user_id", "tenant_id", "token_version"):
        del claims[field]
    with pytest.raises(AuthenticationException):
        await service.authenticate(token=sign_claims(claims))


@pytest.mark.parametrize(
    "field", ["user_id", "tenant_id", "credential_version", "token_version", "sub"]
)
def test_extra_claims_cannot_override_session_identity(
    auth_service: AuthService, field: str
):
    with pytest.raises(ValueError, match="extra_claims may not override"):
        auth_service.create_access_token_for_user(
            TEST_USER, extra_claims={field: "override"}
        )


def test_scoped_mcp_token_uses_the_common_identity_contract(auth_service: AuthService):
    assistant_id, server_id = uuid4(), uuid4()
    token = auth_service.create_scoped_mcp_token(
        TEST_USER, assistant_id=assistant_id, mcp_server_id=server_id
    )
    claims = token_claims(token)
    assert claims["user_id"] == str(TEST_USER.id)
    assert claims["tenant_id"] == str(TEST_USER.tenant_id)
    assert claims["token_version"] == 2
    assert assistant_id_from_token(token) == assistant_id
    assert mcp_server_id_from_token(token) == server_id

    del claims["token_version"]
    legacy = sign_claims(claims)
    for read_scope in (assistant_id_from_token, mcp_server_id_from_token):
        with pytest.raises(AuthenticationException):
            read_scope(legacy)


async def test_identity_bound_session_checks_live_user_and_tenant_state(
    session_service,
):
    service, users = session_service
    token = service.auth_service.create_access_token_for_user(TEST_USER)
    users[TEST_USER.id] = TEST_USER.model_copy(update={"state": UserState.INACTIVE})
    with pytest.raises(UserInactiveException):
        await service.authenticate(token=token)

    users[TEST_USER.id] = TEST_USER.model_copy(
        update={
            "tenant": TEST_USER.tenant.model_copy(
                update={"state": TenantState.SUSPENDED}
            )
        }
    )
    with pytest.raises(TenantSuspendedException):
        await service.authenticate(token=token)
