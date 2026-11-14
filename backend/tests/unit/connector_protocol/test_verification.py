"""A calling installation's assertion is accepted only for the exact request
it was signed for, by the installation's own published key."""

import base64
import time
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from eneo.connector_protocol.verification import (
    Binding,
    body_digest,
    key_digest,
    key_matches,
    unverified_key_id,
    verify_assertion,
)

AUDIENCE = "eneo"
KID = "installation-key-1"
NOW = 1_800_000_000.0
BODY = b'{"actor":{"id":"p1"},"input":{}}'
ACTOR = {
    "id": "p1",
    "name": "Anna Andersson",
    "unitId": "u1",
    "unitLabel": "Bygglov",
    "role": "employee",
}


def _public_jwk(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    numbers = key.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "alg": "RS256",
        "use": "sig",
        "n": b64(numbers.n),
        "e": b64(numbers.e),
    }


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    return {"keys": [_public_jwk(signing_key)]}


def _claims(**changes: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "clew",
        "aud": AUDIENCE,
        "sub": "p1",
        "iat": NOW - 1,
        "exp": NOW + 60,
        "jti": uuid4().hex,
        "actor": dict(ACTOR),
        "body": body_digest(BODY),
        "capability": "eneo.assistants",
    }
    for name, value in changes.items():
        if value is None:
            claims.pop(name, None)
        else:
            claims[name] = value
    return claims


def _sign(
    key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    *,
    kid: str | None = KID,
    typ: str = "JWT",
) -> str:
    headers: dict[str, Any] = {"typ": typ}
    if kid is not None:
        headers["kid"] = kid
    return jwt.encode(claims, key, algorithm="RS256", headers=headers)


BINDING = Binding(body=body_digest(BODY), capability="eneo.assistants")


def _verify(token: str, jwks: Any, *, binding: Binding = BINDING, now: float = NOW):
    return verify_assertion(token, jwks, AUDIENCE, now=now, binding=binding)


def test_accepts_an_assertion_signed_for_this_request(signing_key, jwks):
    actor = _verify(_sign(signing_key, _claims()), jwks)

    assert actor is not None
    assert (actor.id, actor.name, actor.unit_id, actor.unit_label, actor.role) == (
        "p1",
        "Anna Andersson",
        "u1",
        "Bygglov",
        "employee",
    )


def test_accepts_a_route_without_a_capability(signing_key, jwks):
    token = _sign(signing_key, _claims(capability=None))

    assert _verify(token, jwks, binding=Binding(body=body_digest(BODY))) is not None


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"aud": "another-connector"}, id="wrong audience"),
        pytest.param({"aud": [AUDIENCE]}, id="audience as a list"),
        pytest.param({"iss": "someone-else"}, id="wrong issuer"),
        pytest.param({"exp": NOW - 1}, id="expired"),
        pytest.param({"iat": NOW + 30, "exp": NOW + 60}, id="issued in the future"),
        pytest.param({"iat": NOW - 1, "exp": NOW + 121}, id="lifetime over 120 s"),
        pytest.param({"exp": "soon"}, id="expiry that is not a number"),
        pytest.param({"jti": None}, id="no jti"),
        pytest.param({"sub": "p2"}, id="subject is not the actor"),
        pytest.param({"actor": None}, id="no actor"),
        pytest.param({"actor": {**ACTOR, "role": "admin"}}, id="unknown role"),
        pytest.param({"actor": {**ACTOR, "unitId": 7}}, id="actor field not text"),
        pytest.param({"caller": "installation"}, id="the installation's own call"),
        pytest.param({"capability": "eneo.search"}, id="another capability"),
        pytest.param({"capability": None}, id="no capability on its route"),
        pytest.param({"body": body_digest(BODY + b" ")}, id="body differs by a byte"),
        pytest.param({"body": None}, id="not bound to a body"),
    ],
)
def test_refuses_claims_that_do_not_fit_the_request(signing_key, jwks, changes):
    assert _verify(_sign(signing_key, _claims(**changes)), jwks) is None


def test_refuses_a_capability_claim_on_a_route_without_one(signing_key, jwks):
    token = _sign(signing_key, _claims())

    assert _verify(token, jwks, binding=Binding(body=body_digest(BODY))) is None


def test_refuses_a_key_id_the_installation_does_not_publish(signing_key, jwks):
    assert _verify(_sign(signing_key, _claims(), kid="unknown"), jwks) is None
    assert _verify(_sign(signing_key, _claims(), kid=None), jwks) is None


def test_refuses_a_signature_by_another_key(jwks):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert _verify(_sign(other, _claims()), jwks) is None


def test_refuses_a_token_signed_with_a_shared_secret(jwks):
    token = jwt.encode(
        _claims(),
        "wrong-secret-wrong-secret-wrong-secret",
        algorithm="HS256",
        headers={"kid": KID, "typ": "JWT"},
    )

    assert _verify(token, jwks) is None


def test_refuses_a_token_that_is_not_typed_as_a_jwt(signing_key, jwks):
    assert _verify(_sign(signing_key, _claims(), typ="at+jwt"), jwks) is None


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"use": "enc"}, id="a key for encryption"),
        pytest.param({"alg": "RS512"}, id="a key for another algorithm"),
        pytest.param({"kty": "EC"}, id="another key type"),
        pytest.param({"d": "private"}, id="a private key"),
    ],
)
def test_refuses_keys_that_are_not_public_rs256_signing_keys(signing_key, change):
    jwks = {"keys": [{**_public_jwk(signing_key), **change}]}

    assert _verify(_sign(signing_key, _claims()), jwks) is None


def test_refuses_when_two_keys_share_the_id(signing_key):
    key = _public_jwk(signing_key)

    assert _verify(_sign(signing_key, _claims()), {"keys": [key, dict(key)]}) is None


@pytest.mark.parametrize("jwks", [None, {}, {"keys": "none"}, {"keys": [7]}])
def test_refuses_when_there_are_no_usable_keys(signing_key, jwks):
    assert _verify(_sign(signing_key, _claims()), jwks) is None


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c", "a.b"])
def test_refuses_what_is_not_a_token(jwks, token):
    assert _verify(token, jwks) is None


def test_uses_the_callers_clock_not_the_machines(signing_key, jwks):
    token = _sign(signing_key, _claims())

    assert _verify(token, jwks, now=NOW) is not None
    assert _verify(token, jwks, now=time.time()) is None


def test_body_digest_is_unpadded_base64url_of_the_sha256():
    assert body_digest(b"") == "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"


def test_the_shared_key_is_compared_by_its_digest():
    stored = key_digest("the-shared-key")

    assert key_matches("the-shared-key", stored)
    assert not key_matches("the-shared-kez", stored)
    assert not key_matches("", stored)
    assert not key_matches(None, stored)
    assert not key_matches("the-shared-key", "")


def test_reads_the_key_id_without_trusting_the_token(signing_key):
    assert unverified_key_id(_sign(signing_key, _claims())) == KID
    assert unverified_key_id(_sign(signing_key, _claims(), kid=None)) is None
    assert unverified_key_id("not-a-token") is None
