"""Verifying a calling installation's assertion (connector protocol 3).

A pure module: no settings, no network, no clock of its own. The caller hands
in the installation's public keys and the time, so every refusal is a unit
test. It follows the protocol's reference verifier rule for rule; keep the two
in step.

An assertion is a JWT (``RS256``, ``typ: JWT``, with a ``kid``) that the
installation signs for one request to one connector:

- ``iss`` is the protocol's fixed issuer and ``aud`` the connector's id;
- it lives at most two minutes and is not from the future;
- ``sub`` is the person, and ``actor`` describes them as the installation
  sees them (never used here to decide access);
- ``body`` is the SHA-256 of the exact request body, and ``capability`` names
  the capability of the route, absent on any other route.

An assertion with a ``caller`` claim is the installation reading as itself,
with no person behind it, and is never valid on a person's route.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import jwt

ISSUER = "clew"
ALGORITHM = "RS256"
MAX_LIFETIME_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 5
_ACTOR_TEXT_FIELDS = ("id", "name", "unitId", "unitLabel")
_ACTOR_ROLES = ("manager", "employee")


@dataclass(frozen=True, slots=True)
class Actor:
    """The person as the calling installation describes them."""

    id: str
    name: str
    unit_id: str
    unit_label: str
    role: str


@dataclass(frozen=True, slots=True)
class Binding:
    """What a request binds an assertion to.

    ``capability`` is the name in a capability route, or None on a route that
    names none (an assertion for such a route carries no ``capability``).
    """

    body: str
    capability: str | None = None


def body_digest(body: bytes) -> str:
    """SHA-256 of the exact request body, base64url without padding."""
    digest = hashlib.sha256(body).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def key_digest(key: str) -> str:
    """What is stored of a shared key, and what a supplied key is looked up by."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_matches(supplied: str | None, expected_digest: str) -> bool:
    """Whether the supplied shared key is the one behind ``expected_digest``.

    Compared in constant time, digest against digest, so neither the key's
    length nor how much of it matched shows in the time taken.
    """
    if not supplied or not expected_digest:
        return False
    return hmac.compare_digest(key_digest(supplied), expected_digest)


def unverified_key_id(token: str) -> str | None:
    """The ``kid`` an assertion names, read before anything is verified.

    Only ever used to choose among the installation's own keys.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        return None
    return kid if isinstance(kid, str) and kid else None


def _signing_key(jwks: Mapping[str, Any] | None, kid: str) -> jwt.PyJWK | None:
    """The one public RSA signing key with this id, or None."""
    keys = jwks.get("keys") if jwks is not None else None
    if not isinstance(keys, list):
        return None
    matching: list[dict[str, Any]] = []
    for candidate in cast(list[object], keys):
        if not isinstance(candidate, dict):
            continue
        key = cast(dict[str, Any], candidate)
        if (
            key.get("kty") == "RSA"
            and key.get("kid") == kid
            and key.get("alg") == ALGORITHM
            and key.get("use") == "sig"
            # A private key published by mistake is no key to trust.
            and "d" not in key
        ):
            matching.append(key)
    if len(matching) != 1:
        return None
    try:
        return jwt.PyJWK.from_dict(matching[0])
    except jwt.PyJWTError:
        return None


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _verified_claims(
    token: str, jwks: Mapping[str, Any] | None, audience: str, now: float
) -> dict[str, Any] | None:
    """The claims of an assertion signed for this audience and still valid."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return None
    kid = header.get("kid")
    if (
        header.get("alg") != ALGORITHM
        or header.get("typ") != "JWT"
        or not isinstance(kid, str)
    ):
        return None
    key = _signing_key(jwks, kid)
    if key is None:
        return None
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[ALGORITHM],
            # The claims are checked below against the caller's clock, with the
            # protocol's own bounds.
            options={
                "verify_signature": True,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except jwt.PyJWTError:
        return None
    if not _is_number(claims.get("exp")) or not _is_number(claims.get("iat")):
        return None
    exp, iat = float(claims["exp"]), float(claims["iat"])
    if (
        claims.get("iss") != ISSUER
        # One audience, as a string: a list that happens to hold it is refused.
        or claims.get("aud") != audience
        or exp <= now
        or iat > now + MAX_CLOCK_SKEW_SECONDS
        or exp - iat > MAX_LIFETIME_SECONDS
        or not isinstance(claims.get("jti"), str)
    ):
        return None
    return claims


def verify_assertion(
    token: str,
    jwks: Mapping[str, Any] | None,
    audience: str,
    *,
    now: float,
    binding: Binding,
) -> Actor | None:
    """The person an assertion was issued for, or None.

    The assertion must have been issued for exactly this request: its ``body``
    claim the digest of the body received and its ``capability`` claim the
    capability of the route. An assertion therefore cannot be replayed with
    another body or on another route. ``now`` is seconds since the epoch.
    """
    try:
        claims = _verified_claims(token, jwks, audience, now)
        if claims is None or "caller" in claims:
            return None
        described = claims.get("actor")
        if not isinstance(described, dict):
            return None
        actor = cast(dict[str, Any], described)
        if (
            actor.get("id") != claims.get("sub")
            or not all(isinstance(actor.get(k), str) for k in _ACTOR_TEXT_FIELDS)
            or actor.get("role") not in _ACTOR_ROLES
        ):
            return None
        if (
            claims.get("body") != binding.body
            or claims.get("capability") != binding.capability
        ):
            return None
        return Actor(
            id=str(actor["id"]),
            name=str(actor["name"]),
            unit_id=str(actor["unitId"]),
            unit_label=str(actor["unitLabel"]),
            role=str(actor["role"]),
        )
    except Exception:
        # Whatever a hostile token makes of the checks above, it is a refusal.
        return None
