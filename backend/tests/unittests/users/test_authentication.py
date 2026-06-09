from unittest.mock import AsyncMock

import jwt
import pytest
from pydantic import ValidationError

from intric.authentication.auth_service import AuthService
from intric.main.config import get_settings
from intric.main.exceptions import AuthenticationException
from tests.fixtures import TEST_USER

JWT_ALGORITHM = get_settings().jwt_algorithm
JWT_AUDIENCE = get_settings().jwt_audience
JWT_EXPIRY_TIME_MINUTES = get_settings().jwt_expiry_time
JWT_SECRET = get_settings().jwt_secret


@pytest.fixture
def auth_service():
    return AuthService(AsyncMock())


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

        token = auth_service.create_access_token_for_user(
            user=TEST_USER, secret_key=str(JWT_SECRET)
        )
        username = auth_service.get_username_from_token(
            token=token, secret_key=str(JWT_SECRET)
        )
        assert username == TEST_USER.username


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
        auth_service.get_username_from_token(token=wrong_token, secret_key=str(secret))


def test_can_create_api_key_successfully(auth_service: AuthService):
    api_key = auth_service._generate_api_key()
    assert len(api_key) != 0


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
        client_id="intric",
        options={"verify_exp": False},
    )

    assert payload["sub"] == "xjoncer"
