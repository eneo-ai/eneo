"""A fake OpenID provider that signs real ID tokens.

``install`` puts it in place of the shared aiohttp session, the way the other
OIDC tests fake HTTP. It answers discovery, JWKS and the token endpoint.
``authorize`` plays the provider's login page: it reads the authorization URL
Eneo built and returns the code and the RFC 9207 ``iss`` parameter Eneo's
callback receives.

Its settings reproduce providers that differ or misbehave: PKCE enforced or
ignored, the ``iss`` parameter advertised or not, a key marked for another
use, an outage, ``sub`` values that differ per client (with a stable ``oid``
claim beside them), and ID tokens with a wrong ``iss``, ``aud``, ``azp`` or
``nonce``, an unsupported algorithm, a foreign signature, a key of the wrong
type, an expiry in the past or an ``iat`` in the future. ``access_token``
signs the JWT access token a resource server receives.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from eneo.authentication import oidc_resource_server
from eneo.authentication.oidc import profile
from eneo.main.aiohttp_client import aiohttp_client

# Removes a claim from the ID token: ``token_claims={"nonce": DROP}``.
DROP = object()


@cache
def _private_key(kind: str, name: str = "provider") -> Any:
    # Generated once per test process; RSA generation is the slow part.
    if kind == "EC":
        return ec.generate_private_key(ec.SECP256R1())
    if kind == "OKP":
        return ed25519.Ed25519PrivateKey.generate()
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _key_kind(algorithm: str) -> str:
    if algorithm == "EdDSA":
        return "OKP"
    return "EC" if algorithm.startswith("ES") else "RSA"


def _public_jwk(private_key: Any, kid: str, use: str | None) -> dict[str, Any]:
    public = private_key.public_key()
    if isinstance(public, ec.EllipticCurvePublicKey):
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(public))
    elif isinstance(public, ed25519.Ed25519PublicKey):
        jwk = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(public))
    else:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    return {**jwk, "kid": kid, **({"use": use} if use is not None else {})}


def _token_hash(algorithm: str, access_token: str) -> str:
    """The ``at_hash`` of an access token; Ed25519 hashes with SHA-512."""
    if algorithm == "EdDSA":
        digest = hashlib.sha512(access_token.encode()).digest()
    else:
        digest = jwt.get_algorithm_by_name(algorithm).compute_hash_digest(
            access_token.encode()
        )
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()


@dataclass
class AuthorizationResponse:
    code: str
    iss: str | None


@dataclass
class _Grant:
    client_id: str
    redirect_uri: str
    nonce: str | None
    code_challenge: str | None
    code_challenge_method: str | None
    claims: dict[str, Any]


class _Body:
    """The body as a stream, as Eneo reads a provider's answer."""

    def __init__(self, body: bytes):
        self._body = body

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for start in range(0, len(self._body), size):
            yield self._body[start : start + size]


class _Response:
    def __init__(self, payload: dict[str, Any], status: int = 200):
        self._payload = payload
        self.status = status
        self.content_length: int | None = None

    @property
    def content(self) -> _Body:
        return _Body(json.dumps(self._payload).encode())

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> dict[str, Any]:
        # Yield like a network read, so concurrent callers interleave.
        await asyncio.sleep(0)
        return self._payload

    async def text(self) -> str:
        return json.dumps(self._payload)


@dataclass
class FakeOidcProvider:
    issuer: str = "https://idp.example.org"
    client_id: str = "eneo-client"
    client_secret: str = "provider-client-secret"
    # Further registered clients, by client_id: their secrets.
    other_clients: dict[str, str] = field(default_factory=dict)
    # The algorithm the provider signs with and advertises.
    algorithm: str = "RS256"
    # What discovery advertises; None means [algorithm].
    advertised_algorithms: list[str] | None = None
    pkce: Literal["enforce", "ignore"] = "ignore"
    advertise_iss_parameter: bool = False
    # The ``iss`` the authorization response carries; None means the issuer
    # when advertised and none otherwise.
    iss_parameter: str | None = None
    # Claims that replace (or, with DROP, remove) what the provider would send.
    token_claims: dict[str, Any] = field(default_factory=dict)
    # Sign with this header algorithm and key instead: "HS256" uses the
    # client secret, "foreign" an RS256 key that is not in the JWKS, and
    # "ES256-under-rsa-kid" an EC key under the kid of the published RSA key.
    signing_override: str | None = None
    discovery_overrides: dict[str, Any] = field(default_factory=dict)
    # Where the token endpoint and the JWKS are; None means the issuer.
    endpoint_base: str | None = None
    # The JWK's ``use``; None leaves it out.
    key_use: str | None = "sig"
    # Discovery and JWKS answer 503, as during an outage.
    down: bool = False
    # When the person last signed in at the provider (its SSO session).
    session_auth_time: int = field(default_factory=lambda: int(time.time()) - 3600)
    # Each client sees its own ``sub`` for the person (pairwise subjects);
    # the ``oid`` claim stays the same for all of them.
    pairwise_subjects: bool = False
    requests: list[tuple[str, str]] = field(default_factory=list)
    token_requests: list[dict[str, str]] = field(default_factory=list)
    # Every ID token issued, in order.
    id_tokens: list[str] = field(default_factory=list)
    _grants: dict[str, _Grant] = field(default_factory=dict)

    @property
    def discovery_url(self) -> str:
        return f"{self.issuer}/.well-known/openid-configuration"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.issuer}/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.endpoint_base or self.issuer}/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self.endpoint_base or self.issuer}/jwks"

    @property
    def kid(self) -> str:
        return f"{_key_kind(self.algorithm).lower()}-key"

    def discovery(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
            "id_token_signing_alg_values_supported": self.advertised_algorithms
            or [self.algorithm],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        }
        if self.advertise_iss_parameter:
            document["authorization_response_iss_parameter_supported"] = True
        return {**document, **self.discovery_overrides}

    def jwks(self) -> dict[str, Any]:
        return {
            "keys": [
                _public_jwk(
                    _private_key(_key_kind(self.algorithm)), self.kid, self.key_use
                )
            ]
        }

    def federation_config(self, **overrides: Any) -> dict[str, Any]:
        """A tenant's stored federation config registered against this provider."""
        return {
            "provider": "example",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "discovery_endpoint": self.discovery_url,
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
            "token_endpoint_auth_method": "client_secret_post",
            "scopes": ["openid", "email", "profile"],
            "claims_mapping": {"email": "email"},
            **overrides,
        }

    def authorize(self, authorization_url: str, **claims: Any) -> AuthorizationResponse:
        """Sign the person in and return what the provider redirects back with."""
        url = urlsplit(authorization_url)
        assert f"{url.scheme}://{url.netloc}{url.path}" == self.authorization_endpoint
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        assert query["response_type"] == "code"
        code = self.issue_code(
            client_id=query["client_id"],
            redirect_uri=query["redirect_uri"],
            nonce=query.get("nonce"),
            code_challenge=query.get("code_challenge"),
            code_challenge_method=query.get("code_challenge_method"),
            **claims,
        )
        if self.iss_parameter is not None:
            iss = self.iss_parameter
        else:
            iss = self.issuer if self.advertise_iss_parameter else None
        return AuthorizationResponse(code=code, iss=iss)

    def issue_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        nonce: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
        **claims: Any,
    ) -> str:
        code = secrets.token_urlsafe(16)
        self._grants[code] = _Grant(
            client_id=client_id,
            redirect_uri=redirect_uri,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            claims=claims,
        )
        return code

    def _client_authenticated(
        self, data: dict[str, str], headers: dict[str, str], auth: Any
    ) -> str | None:
        basic = headers.get("Authorization", "")
        if auth is not None:
            client_id, secret = auth.login, auth.password
        elif basic.startswith("Basic "):
            client_id, _, secret = (
                base64.b64decode(basic.removeprefix("Basic ")).decode().partition(":")
            )
        else:
            client_id, secret = data.get("client_id"), data.get("client_secret")
        registered = {self.client_id: self.client_secret, **self.other_clients}
        if client_id is None or registered.get(client_id) != secret:
            return None
        return client_id

    def _token_response(
        self, data: dict[str, str], headers: dict[str, str], auth: Any
    ) -> _Response:
        self.token_requests.append(dict(data))
        grant = self._grants.pop(data.get("code", ""), None)
        if grant is None or data.get("grant_type") != "authorization_code":
            return _Response({"error": "invalid_grant"}, 400)
        client_id = self._client_authenticated(data, headers, auth)
        if client_id != grant.client_id:
            return _Response({"error": "invalid_client"}, 401)
        if data.get("redirect_uri") != grant.redirect_uri:
            return _Response({"error": "invalid_grant"}, 400)
        if self.pkce == "enforce":
            verifier = data.get("code_verifier") or ""
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            if (
                grant.code_challenge is None
                or grant.code_challenge_method != "S256"
                or not secrets.compare_digest(challenge, grant.code_challenge)
            ):
                return _Response({"error": "invalid_grant"}, 400)
        access_token = secrets.token_urlsafe(24)
        return _Response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "id_token": self._id_token(grant, access_token),
            }
        )

    def subject_for(self, client_id: str, person: str = "person-0001") -> str:
        """The ``sub`` this client sees for the person."""
        if not self.pairwise_subjects:
            return "subject-0001"
        return (
            "pairwise-"
            + hashlib.sha256(f"{client_id}:{person}".encode()).hexdigest()[:16]
        )

    def access_token(self, *, audience: str, client_id: str, **claims: Any) -> str:
        """A JWT access token for an API, as issued to one client."""
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": self.issuer,
            "aud": audience,
            "azp": client_id,
            "sub": self.subject_for(client_id),
            "oid": "person-0001",
            "iat": now,
            "exp": now + 300,
            "email": "user@example.com",
            **claims,
        }
        payload = {key: value for key, value in payload.items() if value is not DROP}
        return jwt.encode(
            payload,
            _private_key(_key_kind(self.algorithm)),
            algorithm=self.algorithm,
            headers={"kid": self.kid},
        )

    def _id_token(self, grant: _Grant, access_token: str) -> str:
        if self.signing_override == "HS256":
            algorithm, key, kid = "HS256", self.client_secret.encode() * 4, self.kid
        elif self.signing_override == "foreign":
            algorithm, key, kid = "RS256", _private_key("RSA", "foreign"), self.kid
        elif self.signing_override == "ES256-under-rsa-kid":
            algorithm, key, kid = "ES256", _private_key("EC"), self.kid
        else:
            algorithm, key, kid = (
                self.algorithm,
                _private_key(_key_kind(self.algorithm)),
                self.kid,
            )
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": grant.client_id,
            "sub": self.subject_for(grant.client_id),
            "oid": "person-0001",
            "iat": now,
            "exp": now + 300,
            "auth_time": self.session_auth_time,
            "email": "user@example.com",
            "email_verified": True,
            "at_hash": _token_hash(algorithm, access_token),
        }
        if grant.nonce is not None:
            claims["nonce"] = grant.nonce
        claims.update(grant.claims)
        claims.update(self.token_claims)
        # Last, so a DROP removes any claim, at_hash included.
        claims = {key: value for key, value in claims.items() if value is not DROP}
        token = jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})
        self.id_tokens.append(token)
        return token


class _ProviderHttp:
    """The shared aiohttp session's place: routes each URL to its provider."""

    def __init__(self, providers: tuple[FakeOidcProvider, ...]):
        self._providers = providers

    def _owner(self, url: str) -> FakeOidcProvider:
        for provider in self._providers:
            bases = (provider.issuer, provider.endpoint_base or provider.issuer)
            if any(url.startswith(base + "/") for base in bases):
                return provider
        raise AssertionError(f"No fake provider serves {url}")

    def get(self, url: str, **kwargs: Any) -> _Response:
        provider = self._owner(url)
        provider.requests.append(("GET", url))
        if provider.down:
            return _Response({"error": "unavailable"}, 503)
        if url == provider.discovery_url:
            return _Response(provider.discovery())
        if url == provider.jwks_uri:
            return _Response(provider.jwks())
        return _Response({"error": "not_found"}, 404)

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        auth: Any = None,
        **kwargs: Any,
    ) -> _Response:
        provider = self._owner(url)
        provider.requests.append(("POST", url))
        if url != provider.token_endpoint:
            return _Response({"error": "not_found"}, 404)
        return provider._token_response(
            {key: str(value) for key, value in (data or {}).items()},
            headers or {},
            auth,
        )


def install(monkeypatch: pytest.MonkeyPatch, *providers: FakeOidcProvider) -> None:
    """Serve these providers to every HTTP call Eneo makes for OIDC, with
    empty discovery and key caches."""
    http = _ProviderHttp(providers)
    monkeypatch.setattr(aiohttp_client, "session", http)
    monkeypatch.setattr(profile, "_discovery_cache", {})
    monkeypatch.setattr(oidc_resource_server, "_federation_jwks_caches", {})
    monkeypatch.setattr(
        oidc_resource_server, "_jwks_cache", oidc_resource_server.JWKSCache()
    )
