"""``private_key_jwt`` client authentication (RFC 7523 section 2.2).

A confidential client proves its identity to the authorization server by
signing a short-lived JWT with its private key; the server verifies it
against the public key published in the client's JWKS document. Eneo keeps
one key pair per deployment (ES256), publishes the public half next to its
client metadata document, and signs an assertion per token request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from eneo.mcp_servers.domain.entities.mcp_oauth_connection import MCPOAuthSigningKey

CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
PRIVATE_KEY_JWT = "private_key_jwt"
SIGNING_ALGORITHM = "ES256"
# Long enough for clock skew between Eneo and the authorization server,
# short enough that a captured assertion is worthless soon after.
ASSERTION_LIFETIME = timedelta(minutes=5)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638 thumbprint of an EC public key, used as its ``kid``."""
    required = {name: jwk[name] for name in ("crv", "kty", "x", "y")}
    canonical = json.dumps(required, sort_keys=True, separators=(",", ":"))
    return _b64url(hashlib.sha256(canonical.encode()).digest())


def generate_signing_key(now: Optional[datetime] = None) -> MCPOAuthSigningKey:
    """A fresh P-256 key pair: PEM for signing, JWK for publishing."""
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numbers = private.public_key().public_numbers()
    public: dict[str, Any] = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }
    kid = jwk_thumbprint(public)
    return MCPOAuthSigningKey(
        kid=kid,
        algorithm=SIGNING_ALGORITHM,
        private_key_pem=pem,
        public_jwk={"kid": kid, "use": "sig", "alg": SIGNING_ALGORITHM, **public},
        created_at=now or datetime.now(timezone.utc),
    )


def jwks_document(keys: list[MCPOAuthSigningKey]) -> dict[str, Any]:
    """The RFC 7517 key set an authorization server fetches to verify us."""
    return {"keys": [dict(key.public_jwk) for key in keys]}


class ClientAssertionSigner:
    """Mints the assertion a token request carries for ``private_key_jwt``."""

    def __init__(self, key: MCPOAuthSigningKey) -> None:
        self._key = key

    @property
    def kid(self) -> str:
        return self._key.kid

    @property
    def algorithm(self) -> str:
        return self._key.algorithm

    def sign(
        self, *, client_id: str, audience: str, now: Optional[datetime] = None
    ) -> str:
        """An assertion for ``client_id`` toward ``audience``.

        ``iss`` and ``sub`` are both the client id as RFC 7523 requires; the
        audience is the endpoint the request goes to, which every
        authorization server accepts and some insist on. A random ``jti``
        makes each assertion single use.
        """
        issued = now or datetime.now(timezone.utc)
        claims = {
            "iss": client_id,
            "sub": client_id,
            "aud": audience,
            "jti": secrets.token_urlsafe(16),
            "iat": int(issued.timestamp()),
            "exp": int((issued + ASSERTION_LIFETIME).timestamp()),
        }
        return jwt.encode(
            claims,
            self._key.private_key_pem,
            algorithm=self._key.algorithm,
            headers={"kid": self._key.kid, "typ": "JWT"},
        )
