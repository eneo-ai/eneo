"""Token requests carry the resource parameter and the right client
authentication, and token responses are read defensively."""

import base64
from datetime import datetime, timezone

import pytest

from eneo.mcp_servers.infrastructure.oauth.client_assertion import (
    ClientAssertionSigner,
    generate_signing_key,
    jwks_document,
)
from eneo.mcp_servers.infrastructure.oauth.token_client import (
    ID_JAG_JWT_TYP,
    ClientCredential,
    OAuthTokenError,
    choose_client_auth_method,
    client_credentials_grant,
    peek_jwt_typ,
    redeem_id_jag,
    refresh_access_token,
    request_id_jag,
)
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
    unsigned_jwt,
)

PUBLIC = ClientCredential(
    client_id="https://eneo.example/c.json", client_secret=None, auth_method="none"
)
BASIC = ClientCredential(
    client_id="pre", client_secret="s3cret", auth_method="client_secret_basic"
)
POST = ClientCredential(
    client_id="pre", client_secret="s3cret", auth_method="client_secret_post"
)


def test_client_auth_method_follows_the_servers_advertisement():
    assert choose_client_auth_method(None, ("client_secret_basic",)) == "none"
    assert (
        choose_client_auth_method("s", ("none", "client_secret_post"))
        == "client_secret_post"
    )
    assert (
        choose_client_auth_method("s", ("client_secret_basic", "client_secret_post"))
        == "client_secret_basic"
    )
    # RFC 8414 default when the server lists nothing.
    assert choose_client_auth_method("s", ()) == "client_secret_basic"
    # Signing is preferred over no authentication, where the server allows it.
    assert (
        choose_client_auth_method(None, ("private_key_jwt", "none"), can_sign=True)
        == "private_key_jwt"
    )
    assert choose_client_auth_method(None, ("private_key_jwt", "none")) == "none"
    assert choose_client_auth_method(None, ("none",), can_sign=True) == "none"


async def test_private_key_jwt_sends_an_assertion_for_the_endpoint(monkeypatch):
    vendor = FakeAuthorizationServer(
        client_credentials=True, auth_methods=("private_key_jwt",)
    )
    vendor.install(monkeypatch)
    key = generate_signing_key()
    vendor.client_jwks = jwks_document([key])
    credential = ClientCredential(
        client_id="https://eneo.example/c.json",
        client_secret=None,
        auth_method="private_key_jwt",
        signer=ClientAssertionSigner(key),
    )

    response = await client_credentials_grant(
        token_endpoint=f"{vendor.base}/oauth2/token",
        resource=vendor.resource,
        credential=credential,
    )

    assert response.access_token == "access-1"
    form = vendor.token_requests[-1]
    assert form["client_assertion_type"].endswith(":jwt-bearer")
    assert "client_secret" not in form
    assert vendor.assertions[-1]["aud"] == f"{vendor.base}/oauth2/token"
    assert vendor.assertions[-1]["iss"] == "https://eneo.example/c.json"


async def test_refresh_sends_resource_and_rotates(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.live_refresh_tokens.add("refresh-0")
    vendor.install(monkeypatch)

    response = await refresh_access_token(
        token_endpoint=f"{vendor.base}/oauth2/token",
        refresh_token="refresh-0",
        resource=vendor.resource,
        credential=PUBLIC,
    )

    assert response.access_token == "access-1"
    assert response.refresh_token == "refresh-1"
    assert response.expires_at is not None
    assert response.expires_at > datetime.now(timezone.utc)
    assert vendor.token_requests[-1]["resource"] == vendor.resource
    assert vendor.token_requests[-1]["client_id"] == PUBLIC.client_id


async def test_invalid_grant_is_recognised(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)

    with pytest.raises(OAuthTokenError) as info:
        await refresh_access_token(
            token_endpoint=f"{vendor.base}/oauth2/token",
            refresh_token="dead",
            resource=vendor.resource,
            credential=PUBLIC,
        )
    assert info.value.is_invalid_grant
    assert info.value.status_code == 400


async def test_client_secret_basic_puts_the_secret_in_the_header(monkeypatch):
    vendor = FakeAuthorizationServer(
        client_credentials=True, auth_methods=("client_secret_basic",)
    )
    vendor.install(monkeypatch)

    await client_credentials_grant(
        token_endpoint=f"{vendor.base}/oauth2/token",
        resource=vendor.resource,
        credential=BASIC,
        scope="mcp:read",
    )

    request = vendor.requests[-1]
    expected = base64.b64encode(b"pre:s3cret").decode()
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert "client_secret" not in vendor.token_requests[-1]
    assert vendor.token_requests[-1]["scope"] == "mcp:read"


async def test_client_secret_post_puts_the_secret_in_the_form(monkeypatch):
    vendor = FakeAuthorizationServer(
        client_credentials=True, auth_methods=("client_secret_post",)
    )
    vendor.install(monkeypatch)

    await client_credentials_grant(
        token_endpoint=f"{vendor.base}/oauth2/token",
        resource=vendor.resource,
        credential=POST,
    )

    assert vendor.token_requests[-1]["client_secret"] == "s3cret"
    assert "Authorization" not in vendor.requests[-1].headers


async def test_id_jag_legs(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=True)
    vendor.install(monkeypatch)
    idp = ClientCredential(
        client_id="eneo-federation",
        client_secret="s3cret",
        auth_method="client_secret_post",
    )

    assertion = await request_id_jag(
        idp_token_endpoint=vendor.idp_token_endpoint,
        id_token=unsigned_jwt({"sub": "u"}),
        authorization_server_issuer=vendor.issuer,
        resource=vendor.resource,
        credential=idp,
        scope="mcp:read",
    )
    assert peek_jwt_typ(assertion) == ID_JAG_JWT_TYP
    leg1 = vendor.token_requests[-1]
    assert leg1["audience"] == vendor.issuer
    assert leg1["resource"] == vendor.resource

    response = await redeem_id_jag(
        token_endpoint=f"{vendor.base}/oauth2/token",
        assertion=assertion,
        resource=vendor.resource,
        credential=PUBLIC,
    )
    assert response.access_token == "access-1"
    assert response.refresh_token is None


async def test_an_assertion_of_the_wrong_type_is_refused(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=True)
    vendor.install(monkeypatch)
    plain = unsigned_jwt({"sub": "u"})  # typ JWT, not oauth-id-jag+jwt

    def hand_out_plain_token(request):
        if request.url.path == "/idp/token":
            import httpx

            return httpx.Response(200, json={"access_token": plain})
        return vendor.handle(request)

    import httpx

    from eneo.mcp_servers.infrastructure.oauth import token_client

    monkeypatch.setattr(
        token_client,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(hand_out_plain_token)),
    )

    with pytest.raises(OAuthTokenError, match="expected 'oauth-id-jag\\+jwt'"):
        await request_id_jag(
            idp_token_endpoint=vendor.idp_token_endpoint,
            id_token=plain,
            authorization_server_issuer=vendor.issuer,
            resource=vendor.resource,
            credential=PUBLIC,
        )
