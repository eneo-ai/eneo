"""The httpx auth that carries an OAuth access token on MCP requests.

It only ever adds ``Authorization: Bearer`` and watches the answer: a 401 or
a 403 ``insufficient_scope`` is recorded as the server's challenge so the
caller can mark the connection and surface the right remedy. It never raises
inside the httpx flow and never reads response bodies, so streaming responses
are untouched.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

import httpx

from eneo.mcp_servers.infrastructure.oauth.discovery import (
    OAuthChallenge,
    parse_challenge,
)


class MCPOAuthBearerAuth(httpx.Auth):
    requires_response_body = False

    def __init__(self, access_token: str) -> None:
        super().__init__()
        self._access_token = access_token
        self.challenge: Optional[OAuthChallenge] = None

    @property
    def denied(self) -> bool:
        return self.challenge is not None

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        response = yield request
        challenge = parse_challenge(response)
        if challenge is not None and (
            challenge.status_code == 401 or challenge.error == "insufficient_scope"
        ):
            self.challenge = challenge
