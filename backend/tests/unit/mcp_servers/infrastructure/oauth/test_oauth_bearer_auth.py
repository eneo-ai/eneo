"""The bearer auth adds the token and records a challenge without raising."""

import httpx

from eneo.mcp_servers.infrastructure.oauth.bearer_auth import MCPOAuthBearerAuth


async def _send(
    status: int, headers: dict[str, str] | None = None
) -> MCPOAuthBearerAuth:
    auth = MCPOAuthBearerAuth("tok")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(status, headers=headers or {})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=auth
    ) as client:
        await client.get("https://vendor.example/mcp")
    assert seen["authorization"] == "Bearer tok"
    return auth


async def test_success_leaves_no_challenge():
    auth = await _send(200)
    assert not auth.denied


async def test_401_records_the_challenge_and_its_scope():
    auth = await _send(
        401,
        {
            "WWW-Authenticate": 'Bearer resource_metadata="https://v/.well-known/oauth-protected-resource", scope="mcp:read"'
        },
    )
    assert auth.denied
    assert auth.challenge is not None
    assert auth.challenge.scope == "mcp:read"
    assert (
        auth.challenge.resource_metadata_url
        == "https://v/.well-known/oauth-protected-resource"
    )


async def test_insufficient_scope_is_a_challenge_but_a_plain_403_is_not():
    step_up = await _send(
        403,
        {"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="mcp:write"'},
    )
    assert step_up.denied and step_up.challenge is not None
    assert step_up.challenge.error == "insufficient_scope"

    forbidden = await _send(403)
    assert not forbidden.denied
