"""Wire-format tests for the ID-JAG strategy.

Pins both legs of the Enterprise-Managed Authorization exchange:

1. Leg 1 to the IdP: token-exchange grant requesting
   ``urn:ietf:params:oauth:token-type:id-jag`` with the ID token as
   subject, ``audience`` = the AS issuer (MUST per the draft) and
   ``resource`` = the MCP resource identifier.
2. Leg 2 to the MCP server's AS: ``jwt-bearer`` grant carrying the
   assertion verbatim.
3. Conformance tripwires: an assertion without the ``oauth-id-jag+jwt``
   JOSE typ is refused (a plain ID/access token must never be forwarded
   to the AS), and an AS token minted for the wrong audience is refused.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest

from eneo.mcp_servers.application.token_exchange import (
    TokenExchangeError,
    TokenExchangeTarget,
)
from eneo.mcp_servers.application.token_exchange import id_jag as id_jag_mod
from eneo.mcp_servers.application.token_exchange.id_jag import IdJagStrategy

IDP_TOKEN_ENDPOINT = "https://idp.example/oauth2/v1/token"
AS_ISSUER = "https://mcp-as.example"
AS_TOKEN_ENDPOINT = "https://mcp-as.example/api/oauth/token"
RESOURCE = "https://mcp.example/mcp/knowledge"


def _jwt(payload: dict[str, Any], typ: str | None = "oauth-id-jag+jwt") -> str:
    header: dict[str, Any] = {"alg": "ES256"}
    if typ is not None:
        header["typ"] = typ

    def b64(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{b64(header)}.{b64(payload)}.sig"


def _id_jag(typ: str | None = "oauth-id-jag+jwt") -> str:
    return _jwt(
        {
            "iss": "https://idp.example",
            "sub": "user-1",
            "aud": AS_ISSUER,
            "resource": RESOURCE,
            "client_id": "eneo-client",
            "jti": "jag-1",
            "exp": int(time.time()) + 300,
        },
        typ=typ,
    )


@pytest.fixture
def patch_post(monkeypatch):
    """Route post_form per endpoint and record every call."""
    state: dict[str, Any] = {"calls": [], "responses": {}}

    async def fake_post(*, token_endpoint, form):
        state["calls"].append({"endpoint": token_endpoint, "form": form})
        return state["responses"][token_endpoint]

    monkeypatch.setattr(id_jag_mod, "post_form", fake_post)
    return state


def _as_access_token() -> str:
    return _jwt(
        {
            "iss": AS_ISSUER,
            "aud": RESOURCE,
            "sub": "user-1",
            "exp": int(time.time()) + 600,
        },
        typ="at+jwt",
    )


async def _run(strategy: IdJagStrategy, **overrides: Any):
    kwargs: dict[str, Any] = dict(
        subject_access_token="idp-at",
        target=TokenExchangeTarget(audience=RESOURCE),
        token_endpoint=IDP_TOKEN_ENDPOINT,
        client_id="eneo-client",
        client_secret="s3cret",
        idp_issuer="https://idp.example",
        subject_id_token="the-id-token",
        as_issuer=AS_ISSUER,
        as_token_endpoint=AS_TOKEN_ENDPOINT,
        scope="knowledge:read",
    )
    kwargs.update(overrides)
    return await strategy.exchange(**kwargs)


@pytest.mark.asyncio
async def test_two_legs_carry_the_normative_parameters(patch_post):
    assertion = _id_jag()
    patch_post["responses"] = {
        IDP_TOKEN_ENDPOINT: (
            200,
            {
                "access_token": assertion,
                "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
            },
        ),
        AS_TOKEN_ENDPOINT: (
            200,
            {"access_token": _as_access_token(), "expires_in": 600},
        ),
    }

    result = await _run(IdJagStrategy())

    leg1, leg2 = patch_post["calls"]
    assert leg1["endpoint"] == IDP_TOKEN_ENDPOINT
    form1 = leg1["form"]
    assert form1["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form1["requested_token_type"] == "urn:ietf:params:oauth:token-type:id-jag"
    assert form1["subject_token"] == "the-id-token"
    assert form1["subject_token_type"] == "urn:ietf:params:oauth:token-type:id_token"
    assert form1["audience"] == AS_ISSUER
    assert form1["resource"] == RESOURCE
    assert form1["scope"] == "knowledge:read"
    assert form1["client_id"] == "eneo-client"
    assert form1["client_secret"] == "s3cret"

    assert leg2["endpoint"] == AS_TOKEN_ENDPOINT
    form2 = leg2["form"]
    assert form2["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert form2["assertion"] == assertion
    assert form2["client_id"] == "eneo-client"
    assert "client_secret" not in form2

    assert result.access_token.startswith("ey") or "." in result.access_token


@pytest.mark.asyncio
async def test_assertion_without_id_jag_typ_is_refused(patch_post):
    patch_post["responses"] = {
        IDP_TOKEN_ENDPOINT: (200, {"access_token": _id_jag(typ="JWT")}),
    }

    with pytest.raises(TokenExchangeError, match="typ"):
        await _run(IdJagStrategy())
    # The AS must never see the malformed assertion.
    assert len(patch_post["calls"]) == 1


@pytest.mark.asyncio
async def test_wrong_issued_token_type_is_refused(patch_post):
    patch_post["responses"] = {
        IDP_TOKEN_ENDPOINT: (
            200,
            {
                "access_token": _id_jag(),
                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
            },
        ),
    }

    with pytest.raises(TokenExchangeError, match="issued token type"):
        await _run(IdJagStrategy())
    assert len(patch_post["calls"]) == 1


@pytest.mark.asyncio
async def test_missing_id_token_is_refused_before_any_call(patch_post):
    with pytest.raises(TokenExchangeError, match="ID token"):
        await _run(IdJagStrategy(), subject_id_token=None)
    assert patch_post["calls"] == []


@pytest.mark.asyncio
async def test_missing_as_coordinates_are_refused_before_any_call(patch_post):
    with pytest.raises(TokenExchangeError, match="authorization"):
        await _run(IdJagStrategy(), as_token_endpoint=None)
    assert patch_post["calls"] == []


@pytest.mark.asyncio
async def test_as_token_with_wrong_audience_is_refused(patch_post):
    wrong_aud = _jwt(
        {
            "iss": AS_ISSUER,
            "aud": "https://other.example/resource",
            "exp": int(time.time()) + 600,
        },
        typ="at+jwt",
    )
    patch_post["responses"] = {
        IDP_TOKEN_ENDPOINT: (200, {"access_token": _id_jag()}),
        AS_TOKEN_ENDPOINT: (200, {"access_token": wrong_aud, "expires_in": 600}),
    }

    with pytest.raises(TokenExchangeError, match="audience"):
        await _run(IdJagStrategy())


@pytest.mark.asyncio
async def test_as_refresh_token_is_captured(patch_post):
    patch_post["responses"] = {
        IDP_TOKEN_ENDPOINT: (200, {"access_token": _id_jag()}),
        AS_TOKEN_ENDPOINT: (
            200,
            {
                "access_token": _as_access_token(),
                "refresh_token": "as-rt",
                "expires_in": 600,
            },
        ),
    }

    result = await _run(IdJagStrategy())
    assert result.refresh_token == "as-rt"
