"""Strategy unit tests: pin the wire format Eneo sends to the IdP.

The broker invariants live in the integration suite; here we pin the
shape of the form payload the RFC 8693 strategy sends so a regression
in the wire translation surfaces immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

from eneo.mcp_servers.application.token_exchange import (
    Rfc8693Strategy,
    TokenExchangeError,
    TokenExchangeTarget,
    TokenExchangeUserActionRequired,
)
from eneo.mcp_servers.application.token_exchange import rfc8693 as rfc8693_mod


@pytest.fixture
def patch_post(monkeypatch):
    """Capture the form payload the strategy POSTs to the IdP."""
    captured: dict[str, Any] = {"endpoint": None, "form": None, "response": None}

    async def fake_post(*, token_endpoint, form):
        captured["endpoint"] = token_endpoint
        captured["form"] = form
        return captured["response"]

    monkeypatch.setattr(rfc8693_mod, "post_form", fake_post)
    return captured


@pytest.mark.asyncio
async def test_keycloak_strategy_emits_rfc8693_form(patch_post):
    patch_post["response"] = (
        200,
        {
            "access_token": "mcp-aud-token",
            "expires_in": 600,
            "scope": "mcp:tools",
        },
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(
        audience="https://mcp.example/srv",
        resource_or_scope="https://mcp.example/srv",
    )
    result = await strat.exchange(
        subject_access_token="user-at",
        target=target,
        token_endpoint="https://kc.example/realms/eneo/protocol/openid-connect/token",
        client_id="eneo-broker",
        client_secret="s3cret",
    )

    form = patch_post["form"]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["subject_token"] == "user-at"
    assert form["subject_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert form["audience"] == "https://mcp.example/srv"
    assert form["resource"] == "https://mcp.example/srv"
    assert (
        form["requested_token_type"] == "urn:ietf:params:oauth:token-type:refresh_token"
    )
    assert "scope" not in form
    assert form["client_id"] == "eneo-broker"
    assert form["client_secret"] == "s3cret"
    assert result.access_token == "mcp-aud-token"
    assert result.scope == "mcp:tools"
    assert result.refresh_token is None


@pytest.mark.asyncio
async def test_rfc8693_strategy_falls_back_to_audience_without_override(patch_post):
    """No override: both audience and resource fall back to target.audience."""
    patch_post["response"] = (
        200,
        {"access_token": "g-token", "expires_in": 60},
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(
        audience="https://mcp.example/g", resource_or_scope=None
    )
    await strat.exchange(
        subject_access_token="ut",
        target=target,
        token_endpoint="https://idp.example/token",
        client_id="cid",
        client_secret=None,
    )

    form = patch_post["form"]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["audience"] == "https://mcp.example/g"
    assert form["resource"] == "https://mcp.example/g"
    assert "client_secret" not in form


@pytest.mark.asyncio
async def test_rfc8693_strategy_override_drives_audience_and_resource(patch_post):
    """An override (per-server or tenant default) wins over the PRM audience."""
    patch_post["response"] = (200, {"access_token": "tok", "expires_in": 60})

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(
        audience="https://mcp.example/g",
        resource_or_scope="eneo-mcp-shared",
    )
    await strat.exchange(
        subject_access_token="ut",
        target=target,
        token_endpoint="https://idp.example/token",
        client_id="cid",
        client_secret=None,
    )

    form = patch_post["form"]
    assert form["audience"] == "eneo-mcp-shared"
    assert form["resource"] == "eneo-mcp-shared"


@pytest.mark.asyncio
async def test_strategy_maps_invalid_grant_to_user_action_required(patch_post):
    patch_post["response"] = (
        400,
        {"error": "invalid_grant", "error_description": "subject token expired"},
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    with pytest.raises(TokenExchangeUserActionRequired):
        await strat.exchange(
            subject_access_token="stale",
            target=target,
            token_endpoint="https://kc.example/token",
            client_id="c",
            client_secret=None,
        )


@pytest.mark.asyncio
async def test_rfc8693_strategy_captures_refresh_token(patch_post):
    """When the IdP returns a refresh_token (offline_access granted), it is captured."""
    patch_post["response"] = (
        200,
        {
            "access_token": "at",
            "refresh_token": "rt-for-audience",
            "expires_in": 300,
        },
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    result = await strat.exchange(
        subject_access_token="user-at",
        target=target,
        token_endpoint="https://idp.example/token",
        client_id="cid",
        client_secret=None,
    )

    assert result.refresh_token == "rt-for-audience"


@pytest.mark.asyncio
async def test_rfc8693_strategy_rejects_unchanged_subject_token(patch_post):
    """Never forward the user's original IdP access token to an MCP server."""
    patch_post["response"] = (
        200,
        {
            "access_token": "user-at",
            "expires_in": 300,
        },
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    with pytest.raises(TokenExchangeError, match="subject access token unchanged"):
        await strat.exchange(
            subject_access_token="user-at",
            target=target,
            token_endpoint="https://idp.example/token",
            client_id="cid",
            client_secret=None,
        )


@pytest.mark.asyncio
async def test_rfc8693_strategy_expired_token_with_refresh_does_not_raise(patch_post):
    """Expired access_token + refresh_token: strategy returns (no raise) so broker can refresh."""
    import base64
    import json
    import time

    expired_exp = int(time.time()) - 3600
    payload_part = base64.urlsafe_b64encode(
        json.dumps({"exp": expired_exp}).encode()
    ).rstrip(b"=")
    expired_jwt = f"hdr.{payload_part.decode()}.sig"

    patch_post["response"] = (
        200,
        {
            "access_token": expired_jwt,
            "refresh_token": "rt-recovery",
            "expires_in": -3600,
        },
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    result = await strat.exchange(
        subject_access_token="user-at",
        target=target,
        token_endpoint="https://idp.example/token",
        client_id="cid",
        client_secret=None,
    )

    assert result.refresh_token == "rt-recovery"
    assert result.access_token == expired_jwt


@pytest.mark.asyncio
async def test_rfc8693_strategy_expired_token_without_refresh_raises(patch_post):
    """Expired access_token + no refresh_token: strategy raises TokenExchangeError."""
    import base64
    import json
    import time

    expired_exp = int(time.time()) - 3600
    payload_part = base64.urlsafe_b64encode(
        json.dumps({"exp": expired_exp}).encode()
    ).rstrip(b"=")
    expired_jwt = f"hdr.{payload_part.decode()}.sig"

    patch_post["response"] = (
        200,
        {
            "access_token": expired_jwt,
            "expires_in": -3600,
        },
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    with pytest.raises(TokenExchangeError, match="already past"):
        await strat.exchange(
            subject_access_token="user-at",
            target=target,
            token_endpoint="https://idp.example/token",
            client_id="cid",
            client_secret=None,
        )


@pytest.mark.asyncio
async def test_strategy_maps_invalid_target_to_token_exchange_error(patch_post):
    patch_post["response"] = (
        400,
        {"error": "invalid_target", "error_description": "audience unknown"},
    )

    strat = Rfc8693Strategy()
    target = TokenExchangeTarget(audience="https://mcp.example/srv")
    with pytest.raises(TokenExchangeError, match="invalid_target"):
        await strat.exchange(
            subject_access_token="ut",
            target=target,
            token_endpoint="https://kc.example/token",
            client_id="c",
            client_secret=None,
        )


def test_classify_error_treats_dead_subject_token_as_user_action():
    """Some IdPs report a stale subject token (rotated signing keys,
    expired assertion) as ``invalid_request`` instead of ``invalid_grant``.
    Both must classify as user-action-required so the broker's one-shot
    refresh retry fires and the user is told to reconnect."""
    from eneo.mcp_servers.application.token_exchange import classify_error

    exc = classify_error(
        400,
        {
            "error": "invalid_request",
            "error_description": "Subject token signature verification failed",
        },
    )
    assert isinstance(exc, TokenExchangeUserActionRequired)

    exc = classify_error(
        400,
        {
            "error": "invalid_request",
            "error_description": "Subject token is expired",
        },
    )
    assert isinstance(exc, TokenExchangeUserActionRequired)


def test_classify_error_keeps_other_invalid_request_as_exchange_error():
    """``invalid_request`` without a subject-token cause stays a plain
    exchange error: it signals broken configuration, not a stale login."""
    from eneo.mcp_servers.application.token_exchange import classify_error

    exc = classify_error(
        400,
        {
            "error": "invalid_request",
            "error_description": "missing required parameter: resource",
        },
    )
    assert isinstance(exc, TokenExchangeError)
    assert not isinstance(exc, TokenExchangeUserActionRequired)


def test_user_action_errors_are_typed_for_transport_consumers():
    """The proxy distinguishes "user can fix by reconnecting SSO" from
    other auth failures via the MCPUserActionRequiredError base; the
    broker's user-facing errors must stay in that hierarchy."""
    from eneo.main.exceptions import (
        MCPAuthenticationError,
        MCPClientError,
        MCPUserActionRequiredError,
    )
    from eneo.mcp_servers.application.mcp_token_broker import (
        MCPNotAuthenticatedError,
    )

    for exc_type in (TokenExchangeUserActionRequired, MCPNotAuthenticatedError):
        assert issubclass(exc_type, MCPUserActionRequiredError)
        assert issubclass(exc_type, MCPAuthenticationError)
        assert issubclass(exc_type, MCPClientError)
