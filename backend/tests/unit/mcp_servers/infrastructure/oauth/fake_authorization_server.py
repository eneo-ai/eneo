"""An in-memory OAuth 2.1 authorization server protecting one MCP server.

Served through ``httpx.MockTransport`` so the discovery, token and connect
code talk to it over their normal HTTP paths. It mirrors what such a vendor
publishes: protected resource metadata, authorization server
metadata (with optional CIMD, DCR, client-credentials and ID-JAG support),
the token endpoint for every grant Eneo uses, registration and revocation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from eneo.mcp_servers.infrastructure.oauth import discovery, token_client

ID_JAG_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unsigned_jwt(payload: dict[str, Any], typ: str = "JWT") -> str:
    header = _b64url(json.dumps({"alg": "none", "typ": typ}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{header}.{body}."


class FakeAuthorizationServer:
    def __init__(
        self,
        *,
        base: str = "https://vendor.example",
        cimd: bool = True,
        dcr: bool = True,
        id_jag: bool = False,
        client_credentials: bool = False,
        iss_param: bool = False,
        scopes: tuple[str, ...] = ("mcp:read", "mcp:write"),
        challenge_scope: Optional[str] = None,
        auth_methods: tuple[str, ...] = ("none",),
        serve_prm: bool = True,
        prm_in_challenge: bool = True,
    ) -> None:
        self.base = base
        self.issuer = base
        self.server_url = f"{base}/mcp"
        self.resource = f"{base}/mcp"
        self.cimd = cimd
        self.dcr = dcr
        self.id_jag = id_jag
        self.client_credentials = client_credentials
        self.iss_param = iss_param
        self.scopes = scopes
        self.challenge_scope = challenge_scope
        self.auth_methods = auth_methods
        self.serve_prm = serve_prm
        self.prm_in_challenge = prm_in_challenge
        self.requests: list[httpx.Request] = []
        self.token_requests: list[dict[str, str]] = []
        self.registrations: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self.codes: dict[str, dict[str, str]] = {}
        self.live_refresh_tokens: set[str] = set()
        self.issued = 0
        self.fail_refresh_with: Optional[str] = None
        self.fail_id_jag_with: Optional[str] = None
        self.idp_token_endpoint = f"{base}/idp/token"
        self.access_token_ttl = 3600

    # -- wiring -------------------------------------------------------------

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def install(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(discovery, "_client", self.client)
        monkeypatch.setattr(token_client, "_client", self.client)
        discovery.reset_discovery_cache()

    # -- helpers for tests ----------------------------------------------------

    def authorize(self, url: str) -> tuple[str, str]:
        """Play the user: accept the authorization request, mint a code.

        Returns ``(code, state)`` as the redirect back to Eneo would carry.
        """
        parts = urlsplit(url)
        assert (
            parts.scheme + "://" + parts.netloc + parts.path
            == f"{self.base}/oauth2/authorize"
        )
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert params["response_type"] == "code"
        assert params["code_challenge_method"] == "S256"
        assert params["resource"] == self.resource
        code = f"code-{secrets.token_hex(4)}"
        self.codes[code] = {
            "challenge": params["code_challenge"],
            "redirect_uri": params["redirect_uri"],
            "client_id": params["client_id"],
            "scope": params.get("scope", ""),
        }
        return code, params["state"]

    def last_access_token(self) -> str:
        return f"access-{self.issued}"

    # -- metadata -------------------------------------------------------------

    def _asm(self) -> dict[str, Any]:
        grants = ["authorization_code", "refresh_token"]
        if self.client_credentials:
            grants.append("client_credentials")
        if self.id_jag:
            grants.append(token_client.JWT_BEARER_GRANT)
        doc: dict[str, Any] = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.base}/oauth2/authorize",
            "token_endpoint": f"{self.base}/oauth2/token",
            "revocation_endpoint": f"{self.base}/oauth2/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": grants,
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(self.auth_methods),
            "scopes_supported": list(self.scopes),
        }
        if self.cimd:
            doc["client_id_metadata_document_supported"] = True
        if self.dcr:
            doc["registration_endpoint"] = f"{self.base}/oauth2/register"
        if self.id_jag:
            doc["authorization_grant_profiles_supported"] = [ID_JAG_PROFILE]
        if self.iss_param:
            doc["authorization_response_iss_parameter_supported"] = True
        return doc

    def _prm(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "authorization_servers": [self.issuer],
            "scopes_supported": list(self.scopes),
            "bearer_methods_supported": ["header"],
        }

    # -- request handling -------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host != urlsplit(self.base).netloc:
            return httpx.Response(404)
        if path == "/mcp":
            auth = request.headers.get("Authorization", "")
            if auth == f"Bearer {self.last_access_token()}" and self.issued:
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": {}}
                )
            challenge = 'Bearer error="invalid_token"'
            if self.prm_in_challenge:
                challenge += (
                    f', resource_metadata="{self.base}/.well-known/'
                    'oauth-protected-resource/mcp"'
                )
            if self.challenge_scope:
                challenge += f', scope="{self.challenge_scope}"'
            return httpx.Response(401, headers={"WWW-Authenticate": challenge})
        if path.startswith("/.well-known/oauth-protected-resource"):
            if not self.serve_prm:
                return httpx.Response(404)
            return httpx.Response(200, json=self._prm())
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=self._asm())
        if path == "/.well-known/openid-configuration":
            return httpx.Response(404)
        if path == "/oauth2/register":
            return self._register(request)
        if path == "/oauth2/token":
            return self._token(request)
        if path == "/oauth2/revoke":
            form = self._form(request)
            self.revoked.append(form.get("token", ""))
            return httpx.Response(200)
        if path == "/idp/token":
            return self._idp_token(request)
        return httpx.Response(404)

    @staticmethod
    def _form(request: httpx.Request) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}

    def _client_auth(
        self, request: httpx.Request, form: dict[str, str]
    ) -> Optional[str]:
        """The authenticated client id, or None when authentication failed."""
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            decoded = base64.b64decode(header[6:]).decode()
            client_id, _, secret = decoded.partition(":")
            return client_id if secret == "s3cret" else None
        if "client_secret" in form:
            return form["client_id"] if form["client_secret"] == "s3cret" else None
        return form.get("client_id")

    def _register(self, request: httpx.Request) -> httpx.Response:
        if not self.dcr:
            return httpx.Response(404)
        payload = json.loads(request.content)
        self.registrations.append(payload)
        response: dict[str, Any] = {
            "client_id": f"dcr-client-{len(self.registrations)}",
            "client_id_issued_at": 1700000000,
            "redirect_uris": payload["redirect_uris"],
            "token_endpoint_auth_method": payload.get("token_endpoint_auth_method"),
        }
        if "none" not in self.auth_methods:
            response["client_secret"] = "s3cret"
        return httpx.Response(201, json=response)

    def _issue(self, scope: str, *, refresh: bool = True) -> httpx.Response:
        self.issued += 1
        body: dict[str, Any] = {
            "access_token": f"access-{self.issued}",
            "token_type": "Bearer",
            "expires_in": self.access_token_ttl,
            "scope": scope,
        }
        if refresh:
            token = f"refresh-{self.issued}"
            self.live_refresh_tokens.add(token)
            body["refresh_token"] = token
        return httpx.Response(200, json=body)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        self.token_requests.append(form)
        client_id = self._client_auth(request, form)
        if client_id is None:
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = form.get("grant_type")
        if form.get("resource") != self.resource:
            return httpx.Response(
                400,
                json={"error": "invalid_target", "error_description": "bad resource"},
            )
        if grant == "authorization_code":
            record = self.codes.pop(form.get("code", ""), None)
            if record is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
            if _b64url(digest) != record["challenge"]:
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_grant",
                        "error_description": "pkce mismatch",
                    },
                )
            if form.get("redirect_uri") != record["redirect_uri"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if client_id != record["client_id"]:
                return httpx.Response(400, json={"error": "invalid_client"})
            return self._issue(record["scope"] or " ".join(self.scopes))
        if grant == "refresh_token":
            if self.fail_refresh_with:
                return httpx.Response(400, json={"error": self.fail_refresh_with})
            token = form.get("refresh_token", "")
            if token not in self.live_refresh_tokens:
                return httpx.Response(400, json={"error": "invalid_grant"})
            # Rotation: the old token dies with its use.
            self.live_refresh_tokens.discard(token)
            return self._issue(" ".join(self.scopes))
        if grant == "client_credentials":
            if not self.client_credentials:
                return httpx.Response(400, json={"error": "unsupported_grant_type"})
            return self._issue(form.get("scope", " ".join(self.scopes)), refresh=False)
        if grant == token_client.JWT_BEARER_GRANT:
            if not self.id_jag:
                return httpx.Response(400, json={"error": "unsupported_grant_type"})
            assertion = form.get("assertion", "")
            if token_client.peek_jwt_typ(assertion) != token_client.ID_JAG_JWT_TYP:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return self._issue(form.get("scope", " ".join(self.scopes)), refresh=False)
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _idp_token(self, request: httpx.Request) -> httpx.Response:
        """The enterprise IdP's token endpoint (ID-JAG leg 1)."""
        form = self._form(request)
        self.token_requests.append(form)
        if self.fail_id_jag_with:
            return httpx.Response(403, json={"error": self.fail_id_jag_with})
        if form.get("grant_type") != token_client.TOKEN_EXCHANGE_GRANT:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        if form.get("requested_token_type") != token_client.ID_JAG_TOKEN_TYPE:
            return httpx.Response(400, json={"error": "invalid_request"})
        if form.get("audience") != self.issuer:
            return httpx.Response(400, json={"error": "invalid_target"})
        assertion = unsigned_jwt(
            {
                "iss": "https://idp.example",
                "sub": "user-1",
                "aud": self.issuer,
                "resource": form.get("resource"),
                "exp": 4102444800,
            },
            typ=token_client.ID_JAG_JWT_TYP,
        )
        return httpx.Response(
            200,
            json={
                "access_token": assertion,
                "issued_token_type": token_client.ID_JAG_TOKEN_TYPE,
                "token_type": "N_A",
                "expires_in": 300,
            },
        )
