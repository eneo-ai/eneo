"""private_key_jwt assertions: the key pair, the published JWK and the
claims an authorization server verifies."""

from datetime import datetime, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from eneo.mcp_servers.infrastructure.oauth.client_assertion import (
    ClientAssertionSigner,
    generate_signing_key,
    jwk_thumbprint,
    jwks_document,
)


def test_a_generated_key_publishes_its_public_half_only():
    key = generate_signing_key()

    assert key.algorithm == "ES256"
    private = serialization.load_pem_private_key(
        key.private_key_pem.encode(), password=None
    )
    assert isinstance(private, ec.EllipticCurvePrivateKey)
    jwk = key.public_jwk
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256"
    assert set(jwk) == {"kid", "use", "alg", "kty", "crv", "x", "y"}
    assert jwk["kid"] == jwk_thumbprint(jwk)
    assert jwks_document([key]) == {"keys": [jwk]}


def test_an_assertion_verifies_against_the_published_key():
    key = generate_signing_key()
    signer = ClientAssertionSigner(key)
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    assertion = signer.sign(
        client_id="https://eneo.example/c.json",
        audience="https://vendor.example/oauth2/token",
        now=now,
    )

    assert jwt.get_unverified_header(assertion) == {
        "alg": "ES256",
        "typ": "JWT",
        "kid": key.kid,
    }
    claims = jwt.decode(
        assertion,
        key=jwt.PyJWK.from_dict(key.public_jwk).key,
        algorithms=["ES256"],
        audience="https://vendor.example/oauth2/token",
        options={"verify_exp": False},
    )
    assert claims["iss"] == claims["sub"] == "https://eneo.example/c.json"
    assert claims["exp"] - claims["iat"] == 300
    again = signer.sign(client_id="c", audience="a", now=now)
    assert (
        jwt.decode(again, options={"verify_signature": False})["jti"] != claims["jti"]
    )
