"""Strategy unit tests — pin the wire format Eneo sends to the IdP.

The broker invariants live in the integration suite; here we pin the
shape of the form payload the RFC 8693 strategy sends so a regression
in the wire translation surfaces immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

from intric.mcp_servers.application import token_exchange as te_mod
from intric.mcp_servers.application.token_exchange import (
    Rfc8693Strategy,
    TokenExchangeError,
    TokenExchangeTarget,
    TokenExchangeUserActionRequired,
)


@pytest.fixture
def patch_post(monkeypatch):
    """Capture the form payload the strategy POSTs to the IdP."""
    captured: dict[str, Any] = {"endpoint": None, "form": None, "response": None}

    async def fake_post(*, token_endpoint, form):
        captured["endpoint"] = token_endpoint
        captured["form"] = form
        return captured["response"]

    monkeypatch.setattr(te_mod, "_post_form", fake_post)
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
        form["requested_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    )
    assert form["client_id"] == "eneo-broker"
    assert form["client_secret"] == "s3cret"
    assert result.access_token == "mcp-aud-token"
    assert result.scope == "mcp:tools"


@pytest.mark.asyncio
async def test_rfc8693_strategy_falls_back_to_audience_without_override(patch_post):
    """No override → both audience and resource fall back to target.audience."""
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
